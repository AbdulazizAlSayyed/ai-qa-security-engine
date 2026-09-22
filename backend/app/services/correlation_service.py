"""Correlation & prioritization of a completed assessment (Phase 6).

    Route -> CorrelationService -> engines/correlation      (group evidence)
                 |                  engines/prioritization   (score, issues)
                 '-> MongoDB: reads assessments, evidence, ai_analysis_logs
                              writes correlation_groups, issues,
                              and assessments.correlation (derived metadata)

An explicit, repeatable operation - never part of the assessment pipeline,
and never dependent on an AI provider. It reads evidence (the source of
truth) and, when one exists, the latest *completed* AI analysis as
supporting metadata. It calls no model, no scanner, no browser and no
target.

Nothing it reads is modified: ``qa_runs``, ``security_runs``, ``evidence``
and ``ai_analysis_logs`` stay as they are, and the assessment's technical
fields and lifecycle state are untouched. The only write to the assessment
is its ``correlation`` summary, which doubles as a lock so two runs cannot
interleave. Groups and issues are upserted on ``(assessment_id, group_key)``,
so running it again updates the same documents and keeps their references.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.engines.correlation.correlator import (
    EvidenceOwnershipError,
    assign_reference_numbers,
    correlate,
    link_ai_findings,
)
from app.engines.correlation.keys import CORRELATION_VERSION
from app.engines.orchestrator.models import AssessmentState
from app.engines.orchestrator.state_machine import utc_now
from app.engines.prioritization.issue_builder import build_group_fields, build_issue_fields
from app.engines.prioritization.scoring import PRIORITY_LEVELS, PRIORITY_MODEL_VERSION
from app.models import ai_analysis as analysis_model
from app.models import assessment as assessment_model
from app.models import correlation_group as group_model
from app.models import evidence as evidence_model
from app.models import issue as issue_model
from app.services.assessment_service import AssessmentNotFoundError, InvalidAssessmentIdError

logger = logging.getLogger(__name__)

#: Upper bound on the evidence read for one run.
MAX_EVIDENCE_LOADED = 5000
MAX_GROUPS_LISTED = 2000


class CorrelationServiceError(Exception):
    """Base class for correlation failures."""


class AssessmentNotProcessableError(CorrelationServiceError):
    """The assessment exists but cannot be processed right now (409)."""


class CorrelationPersistenceError(CorrelationServiceError):
    """MongoDB failed while reading or writing derived data (500)."""


class CorrelationProcessingError(CorrelationServiceError):
    """The stored data broke an integrity rule, e.g. evidence ownership (500)."""


def to_object_id(assessment_id: str) -> ObjectId:
    if not ObjectId.is_valid(assessment_id):
        raise InvalidAssessmentIdError(f"{assessment_id!r} is not a valid assessment id.")
    return ObjectId(assessment_id)


async def read_assessment(db: AsyncDatabase, assessment_id: str) -> dict[str, Any]:
    """400 for a malformed id, 404 for an unknown one."""
    oid = to_object_id(assessment_id)
    try:
        document = await assessment_model.get_collection(db).find_one({"_id": oid})
    except PyMongoError as exc:
        raise CorrelationPersistenceError(
            f"Could not read the assessment: {type(exc).__name__}"
        ) from exc
    if document is None:
        raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
    return document


class CorrelationService:
    """Deterministic correlation and prioritization over stored evidence."""

    def __init__(self, db: AsyncDatabase, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._assessments = assessment_model.get_collection(db)
        self._evidence = evidence_model.get_collection(db)
        self._analyses = analysis_model.get_collection(db)
        self._groups = group_model.get_collection(db)
        self._issues = issue_model.get_collection(db)

    async def ensure_indexes(self) -> None:
        await group_model.ensure_indexes(self._db)
        await issue_model.ensure_indexes(self._db)

    # --- the operation -----------------------------------------------------

    async def process(self, assessment_id: str) -> dict[str, Any]:
        """Correlate, prioritize and persist. Idempotent for unchanged inputs."""
        assessment = await read_assessment(self._db, assessment_id)
        status = assessment.get("status")
        if status != AssessmentState.COMPLETED.value:
            raise AssessmentNotProcessableError(
                "Only a completed assessment can be correlated; this one is "
                f"{status!r}. Try again when it is completed."
            )

        previous = assessment.get("correlation") or {}
        started_at = utc_now()
        await self._lock(assessment["_id"], previous, started_at)

        try:
            summary = await self._run(assessment_id, started_at)
        except EvidenceOwnershipError as exc:
            await self._release_failed(assessment["_id"], previous, started_at, str(exc))
            raise CorrelationProcessingError(
                f"Correlation stopped: {exc} Evidence must belong to the assessment."
            ) from exc
        except CorrelationServiceError as exc:
            await self._release_failed(assessment["_id"], previous, started_at, str(exc))
            raise
        except Exception as exc:
            await self._release_failed(
                assessment["_id"], previous, started_at, f"Unexpected {type(exc).__name__}"
            )
            raise

        await self._release(assessment["_id"], started_at, summary)
        logger.info(
            "Correlation completed: assessment=%s evidence=%d considered=%d groups=%d "
            "priorities=%s ai_analysis=%s",
            assessment_id,
            summary["evidence_total"],
            summary["evidence_considered"],
            summary["group_count"],
            summary["priority_counts"],
            summary["ai_analysis_id"] or "-",
        )
        return {
            "assessment_id": assessment_id,
            "correlation": summary,
            "issues": await self._read_issues(assessment_id),
        }

    async def _run(self, assessment_id: str, started_at: datetime) -> dict[str, Any]:
        evidence = await self._read_evidence(assessment_id)
        outcome = correlate(assessment_id, evidence)
        owned = {str(item["evidence_id"]) for item in evidence}

        analysis = await self._latest_completed_analysis(assessment_id)
        findings = ((analysis or {}).get("result") or {}).get("findings") or []
        linked = link_ai_findings(outcome.groups, findings, owned)
        ai_analysis_id = analysis.get("analysis_id") if analysis else None

        keys = [group.group_key for group in outcome.groups]
        group_numbers = assign_reference_numbers(
            keys, await self._existing_numbers(self._groups, assessment_id, "group_number")
        )
        issue_numbers = assign_reference_numbers(
            keys, await self._existing_numbers(self._issues, assessment_id, "issue_number")
        )

        now = utc_now()
        priority_counts = {level: 0 for level in PRIORITY_LEVELS}
        for group in outcome.groups:
            # Belt and braces: correlate() already checked ownership.
            if not set(group.evidence_ids) <= owned:
                raise EvidenceOwnershipError(
                    f"Group {group.group_key} references evidence outside {assessment_id}."
                )
            key = group.group_key
            group_fields = build_group_fields(assessment_id, group, group_numbers[key])
            issue_fields, priority = build_issue_fields(
                assessment_id,
                group,
                group_numbers[key],
                issue_numbers[key],
                linked.links.get(key, []),
                ai_analysis_id,
            )
            await self._upsert(self._groups, assessment_id, key, group_fields, now)
            await self._upsert(self._issues, assessment_id, key, issue_fields, now)
            priority_counts[priority.priority] += 1

        # Derived records from an earlier rule set that no longer apply. Only
        # this assessment's derived data is touched; evidence never is.
        try:
            await self._groups.delete_many({"assessment_id": assessment_id, "group_key": {"$nin": keys}})
            await self._issues.delete_many({"assessment_id": assessment_id, "group_key": {"$nin": keys}})
        except PyMongoError as exc:
            raise CorrelationPersistenceError(
                f"Could not remove outdated derived records: {type(exc).__name__}"
            ) from exc

        return {
            "status": "completed",
            "started_at": started_at,
            "completed_at": utc_now(),
            "correlation_version": CORRELATION_VERSION,
            "priority_model_version": PRIORITY_MODEL_VERSION,
            "ai_analysis_id": ai_analysis_id,
            "evidence_total": outcome.evidence_total,
            "evidence_considered": outcome.evidence_considered,
            "evidence_excluded": outcome.evidence_excluded,
            "ai_references_ignored": linked.ignored_references,
            "group_count": len(outcome.groups),
            "issue_count": len(outcome.groups),
            "priority_counts": priority_counts,
            "error": None,
        }

    # --- lock on the assessment's correlation summary ------------------------

    async def _lock(self, oid: ObjectId, previous: dict[str, Any], started_at: datetime) -> None:
        stale_before = started_at - timedelta(seconds=self._settings.correlation_stale_seconds)
        running = {**previous, "status": "running", "started_at": started_at, "error": None}
        try:
            result = await self._assessments.update_one(
                {
                    "_id": oid,
                    "status": AssessmentState.COMPLETED.value,
                    "$or": [
                        {"correlation.status": {"$ne": "running"}},
                        {"correlation.started_at": {"$lt": stale_before}},
                    ],
                },
                {"$set": {"correlation": running}},
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(
                f"Could not start correlation: {type(exc).__name__}"
            ) from exc
        if result.matched_count == 0:
            raise AssessmentNotProcessableError(
                "Correlation is already running for this assessment, or it is no longer "
                "completed. Try again shortly."
            )

    async def _release(self, oid: ObjectId, started_at: datetime, summary: dict[str, Any]) -> None:
        try:
            await self._assessments.update_one(
                {"_id": oid, "correlation.started_at": started_at},
                {"$set": {"correlation": summary}},
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(
                f"Could not record the correlation result: {type(exc).__name__}"
            ) from exc

    async def _release_failed(
        self, oid: ObjectId, previous: dict[str, Any], started_at: datetime, message: str
    ) -> None:
        failed = {
            **previous,
            "status": "failed",
            "started_at": started_at,
            "completed_at": utc_now(),
            "error": message[:500],
        }
        try:
            await self._assessments.update_one(
                {"_id": oid, "correlation.started_at": started_at},
                {"$set": {"correlation": failed}},
            )
        except PyMongoError:
            # The stale rule releases the lock later.
            logger.exception("Could not record a failed correlation for %s", oid)

    # --- reads and writes ------------------------------------------------------

    async def _read_evidence(self, assessment_id: str) -> list[dict[str, Any]]:
        try:
            return (
                await self._evidence.find({"assessment_id": assessment_id})
                .sort(evidence_model.LIST_SORT)
                .limit(MAX_EVIDENCE_LOADED)
                .to_list(length=None)
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(f"Could not read evidence: {type(exc).__name__}") from exc

    async def _latest_completed_analysis(self, assessment_id: str) -> dict[str, Any] | None:
        try:
            return await self._analyses.find_one(
                {"assessment_id": assessment_id, "status": "completed"},
                sort=analysis_model.LIST_SORT,
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(
                f"Could not read AI analyses: {type(exc).__name__}"
            ) from exc

    async def _existing_numbers(self, collection, assessment_id: str, field: str) -> dict[str, int]:
        try:
            documents = await collection.find(
                {"assessment_id": assessment_id}, {"group_key": 1, field: 1}
            ).to_list(length=None)
        except PyMongoError as exc:
            raise CorrelationPersistenceError(
                f"Could not read existing derived records: {type(exc).__name__}"
            ) from exc
        return {str(d["group_key"]): int(d[field]) for d in documents if field in d}

    async def _upsert(self, collection, assessment_id: str, key: str, fields: dict[str, Any], now) -> None:
        try:
            await collection.update_one(
                {"assessment_id": assessment_id, "group_key": key},
                {"$set": {**fields, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(
                f"Could not store derived record {key}: {type(exc).__name__}"
            ) from exc

    async def _read_issues(self, assessment_id: str) -> list[dict[str, Any]]:
        try:
            documents = (
                await self._issues.find({"assessment_id": assessment_id})
                .sort(issue_model.LIST_SORT)
                .to_list(length=None)
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(f"Could not read issues: {type(exc).__name__}") from exc
        return [issue_model.document_to_response(d) for d in documents]

    async def list_groups(self, assessment_id: str) -> list[dict[str, Any]]:
        await read_assessment(self._db, assessment_id)
        try:
            documents = (
                await self._groups.find({"assessment_id": assessment_id})
                .sort(group_model.LIST_SORT)
                .limit(MAX_GROUPS_LISTED)
                .to_list(length=None)
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(
                f"Could not read correlation groups: {type(exc).__name__}"
            ) from exc
        return [group_model.document_to_response(d) for d in documents]
