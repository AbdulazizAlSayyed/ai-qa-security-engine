"""Assessment business logic.

Thin by design. The pipeline itself lives in
:class:`~app.engines.orchestrator.orchestrator.AssessmentOrchestrator`; this
service composes it from the existing services and a MongoDB-backed store,
and owns retrieval.

    Route -> AssessmentService -> AssessmentOrchestrator
                                   |- TargetService    (registry lookup)
                                   |- QaService        (real Playwright run)
                                   |- SecurityService  (real ZAP / probes / Semgrep)
                                   '- MongoAssessmentStore

The orchestrator never calls an engine directly, so a pipeline run leaves
exactly the same raw ``qa_runs`` / ``security_runs`` documents a standalone
run would, and the assessment only references them.
"""

from __future__ import annotations

import logging
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.engines.orchestrator.orchestrator import (
    AssessmentError,
    AssessmentOrchestrationError,
    AssessmentOrchestrator,
    AssessmentPersistenceError,
    TargetNotAssessableError,
)
from app.engines.orchestrator.state_machine import utc_now
from app.models import assessment as assessment_model
from app.models import evidence as evidence_model
from app.services.qa_service import QaService
from app.services.security_service import SecurityService
from app.services.target_service import TargetService

logger = logging.getLogger(__name__)

DEFAULT_ASSESSMENT_LIMIT = 25
DEFAULT_EVIDENCE_LIMIT = 500
MAX_EVIDENCE_LIMIT = 2000

__all__ = [
    "AssessmentError",
    "AssessmentNotFoundError",
    "AssessmentOrchestrationError",
    "AssessmentPersistenceError",
    "AssessmentService",
    "InvalidAssessmentIdError",
    "MongoAssessmentStore",
    "TargetNotAssessableError",
]


class InvalidAssessmentIdError(AssessmentError):
    """The supplied assessment id is not a well-formed ObjectId."""


class AssessmentNotFoundError(AssessmentError):
    """No assessment exists with the supplied id."""


def _to_object_id(assessment_id: str) -> ObjectId:
    if not ObjectId.is_valid(assessment_id):
        raise InvalidAssessmentIdError(
            f"{assessment_id!r} is not a valid assessment id."
        )
    return ObjectId(assessment_id)


class MongoAssessmentStore:
    """The orchestrator's persistence port, backed by MongoDB.

    Every driver error becomes :class:`AssessmentPersistenceError`, so the
    orchestrator never sees PyMongo and the API maps it to a single 500.
    """

    def __init__(self, db: AsyncDatabase) -> None:
        self._assessments = assessment_model.get_collection(db)
        self._evidence = evidence_model.get_collection(db)

    async def create(self, document: dict[str, Any]) -> str:
        try:
            result = await self._assessments.insert_one(dict(document))
        except PyMongoError as exc:
            raise AssessmentPersistenceError(
                f"Could not create the assessment: {type(exc).__name__}: {exc}"
            ) from exc
        return str(result.inserted_id)

    async def update(
        self,
        assessment_id: str,
        fields: dict[str, Any],
        transition: dict[str, Any] | None = None,
    ) -> None:
        update: dict[str, Any] = {"$set": {**fields, "updated_at": utc_now()}}
        if transition is not None:
            update["$push"] = {"state_history": transition}
        try:
            await self._assessments.update_one({"_id": ObjectId(assessment_id)}, update)
        except PyMongoError as exc:
            raise AssessmentPersistenceError(
                f"Could not update assessment {assessment_id}: {type(exc).__name__}: {exc}"
            ) from exc

    async def insert_evidence(self, documents: list[dict[str, Any]]) -> None:
        if not documents:
            return
        try:
            await self._evidence.insert_many([dict(document) for document in documents])
        except PyMongoError as exc:
            raise AssessmentPersistenceError(
                f"Could not store {len(documents)} evidence records: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    async def get(self, assessment_id: str) -> dict[str, Any]:
        try:
            document = await self._assessments.find_one({"_id": ObjectId(assessment_id)})
        except PyMongoError as exc:
            raise AssessmentPersistenceError(
                f"Could not read assessment {assessment_id} back: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if document is None:
            raise AssessmentPersistenceError(
                f"Assessment {assessment_id} vanished after being written."
            )
        return assessment_model.document_to_response(document)


class AssessmentService:
    """Runs the full pipeline against a registered target, and reads it back."""

    def __init__(
        self,
        db: AsyncDatabase,
        targets: TargetService,
        qa: QaService,
        security: SecurityService,
        settings: Settings,
    ) -> None:
        self._db = db
        self._assessments = assessment_model.get_collection(db)
        self._evidence = evidence_model.get_collection(db)
        self._settings = settings
        self._orchestrator = AssessmentOrchestrator(
            targets=targets,
            qa=qa,
            security=security,
            store=MongoAssessmentStore(db),
        )

    async def ensure_indexes(self) -> None:
        await assessment_model.ensure_indexes(self._db)
        await evidence_model.ensure_indexes(self._db)

    # --- execution ----------------------------------------------------

    async def run(self, target_id: str) -> dict[str, Any]:
        """Run one full assessment. See :class:`AssessmentOrchestrator`."""
        return await self._orchestrator.run(target_id)

    # --- retrieval ----------------------------------------------------

    async def list_assessments(
        self, limit: int = DEFAULT_ASSESSMENT_LIMIT
    ) -> list[dict[str, Any]]:
        """Recent assessments, newest first."""
        documents = (
            await self._assessments.find({})
            .sort(assessment_model.LIST_SORT)
            .limit(limit)
            .to_list(length=None)
        )
        return [assessment_model.document_to_response(d) for d in documents]

    async def get_assessment(self, assessment_id: str) -> dict[str, Any]:
        document = await self._assessments.find_one({"_id": _to_object_id(assessment_id)})
        if document is None:
            raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
        return assessment_model.document_to_response(document)

    async def get_evidence(
        self, assessment_id: str, limit: int = DEFAULT_EVIDENCE_LIMIT
    ) -> list[dict[str, Any]]:
        """Normalized evidence for one assessment, in normalizer order."""
        await self.get_assessment(assessment_id)  # 400 / 404 first
        documents = (
            await self._evidence.find({"assessment_id": assessment_id})
            .sort(evidence_model.LIST_SORT)
            .limit(limit)
            .to_list(length=None)
        )
        return [evidence_model.document_to_response(d) for d in documents]
