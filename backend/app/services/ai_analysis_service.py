"""Evidence-grounded AI analysis of a completed assessment.

    Route -> AIAnalysisService -> AIProvider (OpenAIProvider in production)
                 |
                 '-> MongoDB: assessments, evidence, ai_analysis_logs

The service reads the assessment and **only** its normalized evidence - the
Phase 4 boundary. It never touches ``qa_runs``, ``security_runs``, a
scanner, a browser or the target. It builds a compact prompt, calls whatever
:class:`AIProvider` it was given, validates the answer deterministically,
and records every execution in ``ai_analysis_logs``.

Failure semantics:

* The technical assessment is never harmed. It goes ``completed ->
  analyzing -> completed`` whatever happens; its summary, run ids and
  evidence are not touched.
* A provider failure or a rejected answer is recorded as a ``failed``
  analysis with a safe message, and surfaced as :class:`AIAnalysisFailedError`.
* Only when MongoDB itself fails is there nothing to record.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.engines.ai.context import EvidenceContext, build_evidence_context, sanitize_text
from app.engines.ai.models import ANALYSIS_VERSION, AnalysisStatus
from app.engines.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.engines.ai.provider import (
    AIProvider,
    AIProviderError,
    ProviderErrorCategory,
    ProviderResult,
)
from app.engines.ai.validation import AnalysisValidationError, validate_analysis
from app.engines.orchestrator.models import AssessmentState
from app.engines.orchestrator.state_machine import is_allowed, utc_now
from app.models import ai_analysis as analysis_model
from app.models import assessment as assessment_model
from app.models import evidence as evidence_model
from app.services.assessment_service import (
    AssessmentNotFoundError,
    InvalidAssessmentIdError,
)

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 20
#: Upper bound on what is loaded for one analysis; the context budget then
#: decides what the model actually sees, and records anything left out.
MAX_EVIDENCE_LOADED = 5000
#: The model's raw answer is kept for audit, bounded.
MAX_RAW_RESPONSE_CHARS = 200_000


class AIAnalysisServiceError(Exception):
    """Base class for analysis failures."""


class AssessmentNotAnalyzableError(AIAnalysisServiceError):
    """The assessment exists but cannot be analysed right now (409)."""


class NoEvidenceError(AIAnalysisServiceError):
    """The assessment has no normalized evidence to analyse (404)."""


class AIAnalysisPersistenceError(AIAnalysisServiceError):
    """MongoDB failed, so the analysis could not be recorded (500)."""


class AIAnalysisFailedError(AIAnalysisServiceError):
    """The analysis ran and was recorded as failed.

    Carries the stored analysis so the caller can point at it. The message
    is platform-written and safe to show.
    """

    def __init__(self, analysis: dict[str, Any]) -> None:
        error = analysis.get("error") or {}
        self.analysis = analysis
        self.category = str(error.get("category", "unknown"))
        super().__init__(
            f"AI analysis {analysis.get('analysis_id')} failed ({self.category}): "
            f"{error.get('message', 'unknown error')}"
        )


def _to_object_id(assessment_id: str) -> ObjectId:
    if not ObjectId.is_valid(assessment_id):
        raise InvalidAssessmentIdError(f"{assessment_id!r} is not a valid assessment id.")
    return ObjectId(assessment_id)


def _safe(message: str) -> str:
    """Belt and braces: no secret-looking text in stored or returned errors."""
    return sanitize_text(message)[0]


class AIAnalysisService:
    """Analyses a completed assessment's evidence through an AIProvider."""

    def __init__(self, db: AsyncDatabase, provider: AIProvider, settings: Settings) -> None:
        self._db = db
        self._provider = provider
        self._settings = settings
        self._assessments = assessment_model.get_collection(db)
        self._evidence = evidence_model.get_collection(db)
        self._analyses = analysis_model.get_collection(db)

    async def ensure_indexes(self) -> None:
        await analysis_model.ensure_indexes(self._db)

    # --- the single path to the model, shared with Phase 8 ---------------------
    # Recommendations are generated through this service rather than through
    # a second provider or client, so every model call still goes
    # AIAnalysisService -> AIProvider -> OpenAIProvider. Additive: analyze()
    # and everything below are unchanged.

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def provider_model(self) -> str:
        return self._provider.model

    async def complete(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        """Send one already-grounded prompt to the configured provider.

        Callers build the prompt from stored data and validate the answer
        themselves. Raises :class:`AIProviderError` exactly as ``analyze``
        experiences it; persists nothing.
        """
        return await self._provider.analyze(system_prompt=system_prompt, user_prompt=user_prompt)

    # --- execution ---------------------------------------------------------

    async def analyze(self, assessment_id: str) -> dict[str, Any]:
        """Run one analysis. Returns the stored analysis when it completed.

        Raises :class:`AIAnalysisFailedError` (after recording the failure)
        when the provider failed or its answer was rejected.
        """
        oid = _to_object_id(assessment_id)
        assessment = await self._read_assessment(oid)
        self._require_analyzable(assessment)

        evidence = await self._read_evidence(assessment_id)
        if not evidence:
            raise NoEvidenceError(
                f"Assessment {assessment_id} has no normalized evidence to analyse."
            )
        # The query already filters by assessment; check anyway, it is cheap.
        foreign = [e.get("evidence_id") for e in evidence if e.get("assessment_id") != assessment_id]
        if foreign:
            raise AIAnalysisPersistenceError(
                f"Evidence lookup for {assessment_id} returned records of another assessment."
            )

        context = build_evidence_context(
            assessment_model.document_to_response(assessment),
            evidence,
            max_items=self._settings.ai_max_evidence_items,
            max_chars=self._settings.ai_max_context_chars,
        )

        analysis_id = uuid.uuid4().hex
        await self._lock(oid, assessment_id, analysis_id)

        started = time.perf_counter()
        now = utc_now()
        document: dict[str, Any] = {
            "analysis_id": analysis_id,
            "assessment_id": assessment_id,
            "target_id": assessment.get("target_id"),
            "provider": self._provider.name,
            "model": self._provider.model,
            "analysis_version": ANALYSIS_VERSION,
            "status": AnalysisStatus.CREATED.value,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
            # Every record the model was shown, as real evidence ids.
            "evidence_ids": context.supplied_evidence_ids,
            "evidence_count": len(context.refs),
            "context": context.metadata(),
            "usage": {},
            "result": None,
            "error": None,
            "raw_response": None,
        }
        try:
            await self._analyses.insert_one(document)
        except PyMongoError as exc:
            await self._unlock(oid, analysis_id, "failed", "AI analysis could not be recorded")
            raise AIAnalysisPersistenceError(
                f"Could not record the analysis: {type(exc).__name__}"
            ) from exc

        logger.info(
            "AI analysis %s started: assessment=%s provider=%s model=%s evidence=%d omitted=%d",
            analysis_id,
            assessment_id,
            self._provider.name,
            self._provider.model or "-",
            len(context.refs),
            len(context.omitted),
        )

        outcome = await self._run(analysis_id, assessment_id, context, started)
        return outcome

    async def _run(
        self,
        analysis_id: str,
        assessment_id: str,
        context: EvidenceContext,
        started: float,
    ) -> dict[str, Any]:
        oid = ObjectId(assessment_id)
        unlock_status = AnalysisStatus.FAILED.value
        unlock_message = f"AI analysis {analysis_id} failed (persistence)"
        try:
            await self._update(
                analysis_id, {"status": AnalysisStatus.RUNNING.value, "started_at": utc_now()}
            )
            fields = await self._execute(analysis_id, assessment_id, context, started)
            await self._update(analysis_id, fields)
            unlock_status = fields["status"]
            unlock_message = f"AI analysis {analysis_id} {unlock_status}" + (
                f" ({fields['error']['category']})" if fields.get("error") else ""
            )
        finally:
            # Whatever happened, the assessment goes back to completed.
            await self._unlock(oid, analysis_id, unlock_status, unlock_message)

        logger.info(
            "AI analysis %s %s: assessment=%s duration=%sms findings=%s error=%s",
            analysis_id,
            fields["status"],
            assessment_id,
            fields.get("duration_ms"),
            len((fields.get("result") or {}).get("findings", [])),
            (fields.get("error") or {}).get("category"),
        )

        stored = await self._read_analysis(analysis_id)
        if stored["status"] != AnalysisStatus.COMPLETED.value:
            raise AIAnalysisFailedError(stored)
        return stored

    async def _execute(
        self,
        analysis_id: str,
        assessment_id: str,
        context: EvidenceContext,
        started: float,
    ) -> dict[str, Any]:
        """Provider call + validation. Returns the fields to store; only
        persistence problems escape as exceptions."""
        try:
            reply = await self._provider.analyze(
                system_prompt=SYSTEM_PROMPT, user_prompt=build_user_prompt(context)
            )
        except AIProviderError as exc:
            return self._failure(
                exc.category.value,
                exc.message,
                started,
                {"status_code": exc.status_code, "provider_code": exc.provider_code},
            )
        except Exception as exc:  # a provider bug is still just a failed analysis
            logger.exception("AI analysis %s: unexpected provider exception", analysis_id)
            return self._failure(
                ProviderErrorCategory.PROVIDER_ERROR.value,
                f"The AI provider failed unexpectedly ({type(exc).__name__}).",
                started,
            )

        fields: dict[str, Any] = {
            "model": reply.model or self._provider.model,
            "usage": reply.usage,
            "raw_response": reply.text[:MAX_RAW_RESPONSE_CHARS],
        }
        try:
            result = validate_analysis(reply.text, context)
            await self._confirm_evidence_ownership(assessment_id, result)
        except AnalysisValidationError as exc:
            code, message, details = await self._explain_rejection(assessment_id, exc)
            fields.update(self._failure(code, message, started, details))
            return fields
        except AIAnalysisPersistenceError:
            raise
        except Exception as exc:
            logger.exception("AI analysis %s: validation crashed", analysis_id)
            fields.update(
                self._failure(
                    "validation_error",
                    f"The answer could not be validated ({type(exc).__name__}), so it was rejected.",
                    started,
                )
            )
            return fields

        fields.update(
            {
                "status": AnalysisStatus.COMPLETED.value,
                "completed_at": utc_now(),
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "result": result.model_dump(),
                "error": None,
            }
        )
        return fields

    def _failure(
        self,
        category: str,
        message: str,
        started: float,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": AnalysisStatus.FAILED.value,
            "completed_at": utc_now(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "result": None,
            "error": {
                "category": category,
                "message": _safe(message),
                "details": {k: v for k, v in (details or {}).items() if v is not None},
            },
        }

    async def _explain_rejection(
        self, assessment_id: str, exc: AnalysisValidationError
    ) -> tuple[str, str, dict[str, Any]]:
        """Name a cross-assessment reference as such, not just 'unknown'."""
        if exc.code == "unknown_evidence_reference":
            unknown = [str(ref) for ref in exc.details.get("unknown", [])]
            try:
                foreign = await self._evidence.find(
                    {"evidence_id": {"$in": unknown}, "assessment_id": {"$ne": assessment_id}},
                    {"evidence_id": 1},
                ).to_list(length=None)
            except PyMongoError:
                foreign = []
            if foreign:
                return (
                    "cross_assessment_reference",
                    f"{exc.details.get('finding_id')} cites evidence that belongs to a "
                    "different assessment. Rejected.",
                    exc.details,
                )
        return exc.code, exc.message, exc.details

    async def _confirm_evidence_ownership(self, assessment_id: str, result: Any) -> None:
        """Every cited evidence_id must still exist and belong to this assessment."""
        cited = {eid for finding in result.findings for eid in finding.evidence_ids}
        if not cited:
            return
        try:
            owned = await self._evidence.count_documents(
                {"evidence_id": {"$in": sorted(cited)}, "assessment_id": assessment_id}
            )
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(
                f"Could not verify evidence ownership: {type(exc).__name__}"
            ) from exc
        if owned != len(cited):
            raise AnalysisValidationError(
                "evidence_not_in_assessment",
                f"{len(cited) - owned} cited evidence record(s) no longer belong to this assessment.",
            )

    # --- assessment lock (completed -> analyzing -> completed) ---------------

    async def _lock(self, oid: ObjectId, assessment_id: str, analysis_id: str) -> None:
        if not is_allowed(AssessmentState.COMPLETED, AssessmentState.ANALYZING):
            raise RuntimeError("The lifecycle table no longer allows completed -> analyzing.")
        now = utc_now()
        stale_before = now - timedelta(seconds=self._settings.ai_analysis_stale_seconds)
        entry = {
            "state": AssessmentState.ANALYZING.value,
            "timestamp": now,
            "message": f"AI analysis {analysis_id} started",
        }
        lock_fields = {
            "status": AssessmentState.ANALYZING.value,
            "ai_analysis_status": AnalysisStatus.RUNNING.value,
            "ai_analysis_id": analysis_id,
            "updated_at": now,
        }
        try:
            # Normal case: completed -> analyzing. The filter makes it atomic,
            # so two concurrent requests cannot both start an analysis.
            result = await self._assessments.update_one(
                {"_id": oid, "status": AssessmentState.COMPLETED.value},
                {"$set": lock_fields, "$push": {"state_history": entry}},
            )
            if result.matched_count == 0:
                # Takeover of an abandoned analysis: record its end first, so
                # the history stays a legal sequence of transitions.
                released = {
                    "state": AssessmentState.COMPLETED.value,
                    "timestamp": now,
                    "message": "Previous AI analysis abandoned (it never finished)",
                }
                result = await self._assessments.update_one(
                    {
                        "_id": oid,
                        "status": AssessmentState.ANALYZING.value,
                        "updated_at": {"$lt": stale_before},
                    },
                    {"$set": lock_fields, "$push": {"state_history": {"$each": [released, entry]}}},
                )
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(
                f"Could not mark the assessment as analysing: {type(exc).__name__}"
            ) from exc

        if result.matched_count == 0:
            raise AssessmentNotAnalyzableError(
                "An AI analysis is already running for this assessment, or it is no longer "
                "completed. Try again when it has finished."
            )

        # A takeover of a stale lock: close the abandoned attempt honestly.
        try:
            await self._analyses.update_many(
                {
                    "assessment_id": assessment_id,
                    "status": {"$in": [AnalysisStatus.CREATED.value, AnalysisStatus.RUNNING.value]},
                    "created_at": {"$lt": stale_before},
                },
                {
                    "$set": {
                        "status": AnalysisStatus.FAILED.value,
                        "completed_at": now,
                        "error": {
                            "category": "abandoned",
                            "message": "The analysis never finished (the server may have stopped).",
                            "details": {},
                        },
                    }
                },
            )
        except PyMongoError:
            logger.warning("Could not close abandoned analyses for %s", assessment_id)

    async def _unlock(self, oid: ObjectId, analysis_id: str, status: str, message: str) -> None:
        """analyzing -> completed. The technical result is left exactly as it was."""
        if not is_allowed(AssessmentState.ANALYZING, AssessmentState.COMPLETED):
            raise RuntimeError("The lifecycle table no longer allows analyzing -> completed.")
        now = utc_now()
        try:
            await self._assessments.update_one(
                {"_id": oid, "status": AssessmentState.ANALYZING.value, "ai_analysis_id": analysis_id},
                {
                    "$set": {
                        "status": AssessmentState.COMPLETED.value,
                        "ai_analysis_status": status,
                        "updated_at": now,
                    },
                    "$push": {
                        "state_history": {
                            "state": AssessmentState.COMPLETED.value,
                            "timestamp": now,
                            "message": message,
                        }
                    },
                },
            )
        except PyMongoError:
            # The stale-lock rule releases it later; the analysis is recorded.
            logger.exception("Could not return assessment %s to completed", oid)

    # --- reads ---------------------------------------------------------------

    def _require_analyzable(self, assessment: dict[str, Any]) -> None:
        status = assessment.get("status")
        if status == AssessmentState.ANALYZING.value:
            return  # _lock decides whether a stale lock may be taken over
        if status != AssessmentState.COMPLETED.value:
            raise AssessmentNotAnalyzableError(
                f"Only a completed assessment can be analysed; this one is {status!r}."
            )

    async def _read_assessment(self, oid: ObjectId) -> dict[str, Any]:
        try:
            document = await self._assessments.find_one({"_id": oid})
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(f"Could not read the assessment: {type(exc).__name__}") from exc
        if document is None:
            raise AssessmentNotFoundError(f"No assessment with id {oid}.")
        return document

    async def _read_evidence(self, assessment_id: str) -> list[dict[str, Any]]:
        try:
            return (
                await self._evidence.find({"assessment_id": assessment_id})
                .sort(evidence_model.LIST_SORT)
                .limit(MAX_EVIDENCE_LOADED)
                .to_list(length=None)
            )
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(f"Could not read evidence: {type(exc).__name__}") from exc

    async def _update(self, analysis_id: str, fields: dict[str, Any]) -> None:
        try:
            await self._analyses.update_one({"analysis_id": analysis_id}, {"$set": fields})
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(
                f"Could not update analysis {analysis_id}: {type(exc).__name__}"
            ) from exc

    async def _read_analysis(self, analysis_id: str) -> dict[str, Any]:
        try:
            document = await self._analyses.find_one({"analysis_id": analysis_id})
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(f"Could not read analysis back: {type(exc).__name__}") from exc
        if document is None:
            raise AIAnalysisPersistenceError(f"Analysis {analysis_id} vanished after being written.")
        return analysis_model.document_to_response(document)

    async def latest(self, assessment_id: str) -> dict[str, Any]:
        """The latest attempt and the latest completed analysis, if any."""
        oid = _to_object_id(assessment_id)
        await self._read_assessment(oid)
        try:
            attempt = await self._analyses.find_one(
                {"assessment_id": assessment_id}, sort=analysis_model.LIST_SORT
            )
            completed = await self._analyses.find_one(
                {"assessment_id": assessment_id, "status": AnalysisStatus.COMPLETED.value},
                sort=analysis_model.LIST_SORT,
            )
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(f"Could not read analyses: {type(exc).__name__}") from exc

        return {
            "assessment_id": assessment_id,
            "status": attempt["status"] if attempt else "not_analyzed",
            "latest": analysis_model.document_to_response(attempt) if attempt else None,
            "latest_completed": (
                analysis_model.document_to_response(completed) if completed else None
            ),
        }

    async def history(self, assessment_id: str, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict[str, Any]]:
        oid = _to_object_id(assessment_id)
        await self._read_assessment(oid)
        try:
            documents = (
                await self._analyses.find({"assessment_id": assessment_id})
                .sort(analysis_model.LIST_SORT)
                .limit(limit)
                .to_list(length=None)
            )
        except PyMongoError as exc:
            raise AIAnalysisPersistenceError(f"Could not read analyses: {type(exc).__name__}") from exc
        return [analysis_model.document_to_response(d) for d in documents]
