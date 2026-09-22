"""Advisory recommendation generation (Phase 8).

    Route -> RecommendationService
               |- reads: assessments, issues, correlation_groups, evidence,
               |         ai_analysis_logs (via AIAnalysisService.latest)
               |- engines/remediation: context, prompt, validation
               |- AIAnalysisService.complete -> AIProvider -> OpenAIProvider
               '- writes: recommendations, assessments.recommendation (summary)

Preconditions, all checked server-side (409 when not met):

* the assessment is ``completed`` (not running, failed or being analysed);
* it has a completed AI analysis;
* it was correlated, and that correlation used this same AI analysis - so
  issues and AI findings are never mixed across analysis versions;
* correlation produced at least one issue.

Advisory only. This module runs no command, touches no file, calls no
scanner or target, and writes nothing but ``recommendations`` and the
assessment's ``recommendation`` summary (which doubles as a lock). Issues,
evidence, priorities, severities, AI analyses and the assessment's
technical result are only read.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.engines.ai.context import sanitize_text
from app.engines.ai.provider import AIProviderError, ProviderErrorCategory
from app.engines.ai.validation import AnalysisValidationError
from app.engines.orchestrator.models import AssessmentState
from app.engines.orchestrator.state_machine import utc_now
from app.engines.remediation.context import build_recommendation_context
from app.engines.remediation.models import RECOMMENDATION_VERSION
from app.engines.remediation.prompts import SYSTEM_PROMPT, build_user_prompt
from app.engines.remediation.validation import validate_recommendations
from app.models import assessment as assessment_model
from app.models import correlation_group as group_model
from app.models import evidence as evidence_model
from app.models import issue as issue_model
from app.models import recommendation as recommendation_model
from app.services.ai_analysis_service import AIAnalysisService
from app.services.assessment_service import AssessmentNotFoundError, InvalidAssessmentIdError

logger = logging.getLogger(__name__)

MAX_ISSUES_LOADED = 500
REC_ID_PATTERN = re.compile(r"^REC-(\d{3,})$")


class RecommendationServiceError(Exception):
    """Base class for recommendation failures."""


class RecommendationPrerequisiteError(RecommendationServiceError):
    """The assessment is not in a state recommendations can be generated from (409)."""


class RecommendationPersistenceError(RecommendationServiceError):
    """MongoDB failed (500)."""


class InvalidRecommendationIdError(RecommendationServiceError):
    """Not of the form REC-### (400)."""


class RecommendationNotFoundError(RecommendationServiceError):
    """No such recommendation (404)."""


class RecommendationGenerationFailedError(RecommendationServiceError):
    """The generation ran and was recorded as failed (502, or 503 when unconfigured)."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(f"Recommendation generation failed ({category}): {message}")


def _to_object_id(assessment_id: str) -> ObjectId:
    if not ObjectId.is_valid(assessment_id):
        raise InvalidAssessmentIdError(f"{assessment_id!r} is not a valid assessment id.")
    return ObjectId(assessment_id)


class RecommendationService:
    def __init__(self, db: AsyncDatabase, analysis: AIAnalysisService, settings: Settings) -> None:
        self._analysis = analysis
        self._settings = settings
        self._assessments = assessment_model.get_collection(db)
        self._issues = issue_model.get_collection(db)
        self._groups = group_model.get_collection(db)
        self._evidence = evidence_model.get_collection(db)
        self._recommendations = recommendation_model.get_collection(db)

    # --- generation -----------------------------------------------------------------

    async def generate(self, assessment_id: str) -> dict[str, Any]:
        oid = _to_object_id(assessment_id)
        assessment = await self._read_assessment(oid)
        status = assessment.get("status")
        if status != AssessmentState.COMPLETED.value:
            raise RecommendationPrerequisiteError(
                "Recommendations need a completed assessment that is not being analysed; "
                f"this one is {status!r}."
            )

        analysis = (await self._analysis.latest(assessment_id)).get("latest_completed")
        if not analysis or analysis.get("result") is None:
            raise RecommendationPrerequisiteError(
                "Recommendations need a completed AI analysis of this assessment. Run Analyze first."
            )
        analysis_id = str(analysis["analysis_id"])

        correlation = assessment.get("correlation") or {}
        if correlation.get("status") != "completed":
            raise RecommendationPrerequisiteError(
                "Recommendations need prioritized issues. Run Correlate & Prioritize first."
            )
        if correlation.get("ai_analysis_id") != analysis_id:
            raise RecommendationPrerequisiteError(
                "The prioritized issues were built from a different AI analysis than the latest "
                f"completed one ({analysis_id[:8]}…). Re-run Correlate & Prioritize so issues and "
                "AI findings come from the same analysis."
            )

        issues = await self._find(self._issues, {"assessment_id": assessment_id}, issue_model.LIST_SORT, MAX_ISSUES_LOADED)
        if not issues:
            raise RecommendationPrerequisiteError(
                "Correlation found no issues, so there is nothing to recommend."
            )
        groups = {
            str(g["group_key"]): g
            for g in await self._find(self._groups, {"assessment_id": assessment_id}, group_model.LIST_SORT, None)
        }
        wanted = sorted({eid for issue in issues for eid in issue.get("evidence_ids") or []})
        evidence = await self._find(
            self._evidence,
            {"assessment_id": assessment_id, "evidence_id": {"$in": wanted}},
            evidence_model.LIST_SORT,
            None,
        )

        context = build_recommendation_context(
            assessment=assessment_model.document_to_response(assessment),
            issues=issues,
            groups=groups,
            evidence=evidence,
            analysis_result=analysis.get("result"),
            max_issues=self._settings.recommendation_max_issues,
            max_items=self._settings.ai_max_evidence_items,
            max_chars=self._settings.ai_max_context_chars,
        )

        generation_id = uuid.uuid4().hex
        started_at = utc_now()
        previous = assessment.get("recommendation") or {}
        await self._lock(oid, previous, generation_id, started_at, analysis_id)

        started = time.perf_counter()
        base = {
            "generation_id": generation_id,
            "started_at": started_at,
            "ai_analysis_id": analysis_id,
            "correlation_completed_at": correlation.get("completed_at"),
            "provider": self._analysis.provider_name,
            "model": self._analysis.provider_model,
            "recommendation_version": RECOMMENDATION_VERSION,
            **context.metadata(),
        }
        try:
            summary = await self._run(assessment_id, context, base, started)
        except RecommendationServiceError as exc:
            if not isinstance(exc, RecommendationGenerationFailedError):
                await self._release(oid, generation_id, self._failed(base, started, "persistence", str(exc)))
            raise
        except Exception as exc:
            await self._release(
                oid, generation_id, self._failed(base, started, "internal_error", type(exc).__name__)
            )
            raise
        await self._release(oid, generation_id, summary)
        logger.info(
            "Recommendations generated: assessment=%s analysis=%s count=%d provider=%s",
            assessment_id,
            analysis_id,
            summary["recommendation_count"],
            summary["provider"],
        )
        return await self.view(assessment_id)

    async def _run(self, assessment_id: str, context, base: dict[str, Any], started: float) -> dict[str, Any]:
        oid = ObjectId(assessment_id)
        try:
            reply = await self._analysis.complete(
                system_prompt=SYSTEM_PROMPT, user_prompt=build_user_prompt(context)
            )
        except AIProviderError as exc:
            return await self._fail_generation(oid, base, started, exc.category.value, exc.message)
        except Exception as exc:  # a provider bug is still a failed generation
            logger.exception("Recommendation generation: unexpected provider exception")
            return await self._fail_generation(
                oid,
                base,
                started,
                ProviderErrorCategory.PROVIDER_ERROR.value,
                f"The AI provider failed unexpectedly ({type(exc).__name__}).",
            )

        try:
            records = validate_recommendations(
                reply.text,
                context,
                ai_analysis_id=base["ai_analysis_id"],
                generation_id=base["generation_id"],
                correlation_completed_at=base["correlation_completed_at"],
            )
            await self._confirm_ownership(assessment_id, records)
        except AnalysisValidationError as exc:
            return await self._fail_generation(oid, base, started, exc.code, exc.message)

        now = utc_now()
        keys = [r.issue_id for r in records]
        try:
            for record in records:
                await self._recommendations.update_one(
                    {
                        "assessment_id": assessment_id,
                        "ai_analysis_id": record.ai_analysis_id,
                        "issue_id": record.issue_id,
                    },
                    {"$set": {**record.model_dump(), "updated_at": now}, "$setOnInsert": {"created_at": now}},
                    upsert=True,
                )
            # Same source analysis, advice no longer given in this generation.
            # Sets generated from other AI analyses are left untouched.
            await self._recommendations.delete_many(
                {
                    "assessment_id": assessment_id,
                    "ai_analysis_id": base["ai_analysis_id"],
                    "issue_id": {"$nin": keys},
                }
            )
        except PyMongoError as exc:
            raise RecommendationPersistenceError(
                f"Could not store recommendations: {type(exc).__name__}"
            ) from exc

        return {
            **base,
            "status": "completed",
            "completed_at": utc_now(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "recommendation_count": len(records),
            "usage": {k: int(v) for k, v in (reply.usage or {}).items() if isinstance(v, (int, float))},
            "error": None,
        }

    def _failed(self, base: dict[str, Any], started: float, category: str, message: str) -> dict[str, Any]:
        return {
            **base,
            "status": "failed",
            "completed_at": utc_now(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "recommendation_count": 0,
            "error": {"category": category, "message": sanitize_text(message)[0][:1000]},
        }

    async def _fail_generation(
        self, oid: ObjectId, base: dict[str, Any], started: float, category: str, message: str
    ) -> dict[str, Any]:
        """Record the failure (existing recommendations stay as they were), then raise."""
        summary = self._failed(base, started, category, message)
        await self._release(oid, base["generation_id"], summary)
        logger.warning("Recommendation generation %s failed: %s", base["generation_id"], category)
        raise RecommendationGenerationFailedError(category, summary["error"]["message"])

    async def _confirm_ownership(self, assessment_id: str, records) -> None:
        """Every referenced issue and evidence record must belong to this assessment."""
        issue_ids = sorted({i for r in records for i in r.issue_ids})
        evidence_ids = sorted(
            {e for r in records for e in [*r.evidence_ids, *(c.evidence_id for c in r.retest.checks)]}
        )
        try:
            owned_issues = await self._issues.count_documents(
                {"assessment_id": assessment_id, "issue_id": {"$in": issue_ids}}
            ) if issue_ids else 0
            owned_evidence = await self._evidence.count_documents(
                {"assessment_id": assessment_id, "evidence_id": {"$in": evidence_ids}}
            ) if evidence_ids else 0
        except PyMongoError as exc:
            raise RecommendationPersistenceError(
                f"Could not verify ownership: {type(exc).__name__}"
            ) from exc
        if owned_issues != len(issue_ids) or owned_evidence != len(evidence_ids):
            raise AnalysisValidationError(
                "cross_assessment_reference",
                "A recommendation references an issue or evidence record outside this assessment.",
            )

    # --- lock on the assessment's recommendation summary ---------------------------------

    async def _lock(self, oid, previous, generation_id, started_at, analysis_id) -> None:
        stale_before = started_at - timedelta(seconds=self._settings.ai_analysis_stale_seconds)
        running = {
            **previous,
            "status": "running",
            "generation_id": generation_id,
            "started_at": started_at,
            "ai_analysis_id": analysis_id,
            "error": None,
        }
        try:
            result = await self._assessments.update_one(
                {
                    "_id": oid,
                    "status": AssessmentState.COMPLETED.value,
                    "$or": [
                        {"recommendation.status": {"$ne": "running"}},
                        {"recommendation.started_at": {"$lt": stale_before}},
                    ],
                },
                {"$set": {"recommendation": running}},
            )
        except PyMongoError as exc:
            raise RecommendationPersistenceError(
                f"Could not start generation: {type(exc).__name__}"
            ) from exc
        if result.matched_count == 0:
            raise RecommendationPrerequisiteError(
                "Recommendations are already being generated for this assessment, or it is no "
                "longer completed. Try again shortly."
            )

    async def _release(self, oid: ObjectId, generation_id: str, summary: dict[str, Any]) -> None:
        try:
            await self._assessments.update_one(
                {"_id": oid, "recommendation.generation_id": generation_id},
                {"$set": {"recommendation": summary}},
            )
        except PyMongoError:
            logger.exception("Could not record the recommendation summary for %s", oid)

    # --- reads ------------------------------------------------------------------------------

    async def _read_assessment(self, oid: ObjectId) -> dict[str, Any]:
        try:
            document = await self._assessments.find_one({"_id": oid})
        except PyMongoError as exc:
            raise RecommendationPersistenceError(f"Could not read the assessment: {type(exc).__name__}") from exc
        if document is None:
            raise AssessmentNotFoundError(f"No assessment with id {oid}.")
        return document

    async def _find(self, collection, query, sort, limit) -> list[dict[str, Any]]:
        try:
            cursor = collection.find(query).sort(sort)
            if limit:
                cursor = cursor.limit(limit)
            return await cursor.to_list(length=None)
        except PyMongoError as exc:
            raise RecommendationPersistenceError(f"Could not read source data: {type(exc).__name__}") from exc

    async def _shown_analysis_id(self, assessment_id: str, requested: str | None) -> str | None:
        if requested:
            return requested
        try:
            newest = await self._recommendations.find_one(
                {"assessment_id": assessment_id}, sort=[("updated_at", -1), ("_id", -1)]
            )
        except PyMongoError as exc:
            raise RecommendationPersistenceError(f"Could not read recommendations: {type(exc).__name__}") from exc
        return str(newest["ai_analysis_id"]) if newest else None

    async def view(self, assessment_id: str, ai_analysis_id: str | None = None) -> dict[str, Any]:
        oid = _to_object_id(assessment_id)
        assessment = await self._read_assessment(oid)
        latest = (await self._analysis.latest(assessment_id)).get("latest_completed")
        current = str(latest["analysis_id"]) if latest else None
        shown = await self._shown_analysis_id(assessment_id, ai_analysis_id)

        try:
            items = (
                await self._find(
                    self._recommendations,
                    {"assessment_id": assessment_id, "ai_analysis_id": shown},
                    recommendation_model.LIST_SORT,
                    None,
                )
                if shown
                else []
            )
            sets = await (
                await self._recommendations.aggregate(
                    [
                        {"$match": {"assessment_id": assessment_id}},
                        {"$group": {"_id": "$ai_analysis_id", "count": {"$sum": 1}, "updated_at": {"$max": "$updated_at"}}},
                        {"$sort": {"updated_at": -1}},
                    ]
                )
            ).to_list(length=None)
        except PyMongoError as exc:
            raise RecommendationPersistenceError(f"Could not read recommendations: {type(exc).__name__}") from exc

        correlation_at = (assessment.get("correlation") or {}).get("completed_at")
        is_current = bool(
            items
            and shown == current
            and all(item.get("correlation_completed_at") == correlation_at for item in items)
        )
        summary = assessment.get("recommendation")
        return {
            "assessment_id": assessment_id,
            "status": (summary or {}).get("status", "not_generated"),
            "generation": summary,
            "current_ai_analysis_id": current,
            "ai_analysis_id": shown,
            "is_current": is_current,
            "sets": [
                {"ai_analysis_id": str(s["_id"]), "count": int(s["count"]), "updated_at": s["updated_at"]}
                for s in sets
            ],
            "recommendations": [recommendation_model.document_to_response(d) for d in items],
        }

    async def get(self, assessment_id: str, recommendation_id: str, ai_analysis_id: str | None = None) -> dict[str, Any]:
        oid = _to_object_id(assessment_id)
        await self._read_assessment(oid)
        match = REC_ID_PATTERN.match(recommendation_id)
        if not match:
            raise InvalidRecommendationIdError(
                f"{recommendation_id!r} is not a valid recommendation reference (REC-###)."
            )
        shown = await self._shown_analysis_id(assessment_id, ai_analysis_id)
        document = None
        if shown:
            try:
                document = await self._recommendations.find_one(
                    {
                        "assessment_id": assessment_id,
                        "ai_analysis_id": shown,
                        "recommendation_number": int(match.group(1)),
                    }
                )
            except PyMongoError as exc:
                raise RecommendationPersistenceError(f"Could not read the recommendation: {type(exc).__name__}") from exc
        if document is None:
            raise RecommendationNotFoundError(f"No recommendation {recommendation_id} in assessment {assessment_id}.")
        return recommendation_model.document_to_response(document)
