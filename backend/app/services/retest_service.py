"""Retest execution (Phase 9).

    Route -> RetestService
               |- resolves, server-side: assessment -> recommendation -> retest spec
               |                          -> issue -> evidence -> AI analysis -> target
               |- engines/retest/plan.py     scoped plan (which engine, which part)
               |- QaService.run(checks=...) / SecurityService.run(components=...)
               |     (the existing engines; raw runs land in qa_runs / security_runs)
               |- engines/orchestrator/normalizer   (existing normalization, in memory)
               |- engines/retest/verdict.py  deterministic PASS / FAIL (Phase 6 keys)
               '- writes: retests only

The client sends nothing but the recommendation reference; the stored
specification is what runs. Execution status (running / completed /
failed) and verdict (PASS / FAIL) are separate: an engine that could not
execute is ``failed`` with no verdict, never a FAIL.

History: every execution is a new ``RETEST-###`` document; nothing is
overwritten or deleted, and numbers are never reused. The original
assessment, its evidence, issues, correlation groups, AI analyses and
recommendations are only read - the assessment stays ``completed``.
Synchronous, like the rest of the platform; no AI is involved.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from typing import Any

from bson import ObjectId
from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.config import Settings
from app.engines.orchestrator.models import AssessmentState
from app.engines.orchestrator.normalizer import normalize_qa_run, normalize_security_run
from app.engines.orchestrator.state_machine import utc_now
from app.engines.remediation.models import RetestSpecification
from app.engines.retest.plan import RetestNotEligibleError, plan_retest
from app.engines.retest.verdict import evaluate, execution_problem
from app.models import ai_analysis as analysis_model
from app.models import assessment as assessment_model
from app.models import evidence as evidence_model
from app.models import issue as issue_model
from app.models import recommendation as recommendation_model
from app.models import retest as retest_model
from app.services.assessment_service import AssessmentNotFoundError, InvalidAssessmentIdError
from app.services.qa_service import QaService, QaServiceError
from app.services.security_service import SecurityService, SecurityServiceError
from app.services.target_service import TargetServiceError

logger = logging.getLogger(__name__)

RETEST_VERSION = "1.0"
REC_ID_PATTERN = re.compile(r"^REC-(\d{3,})$")
RETEST_ID_PATTERN = re.compile(r"^RETEST-(\d{3,})$")
ANALYSIS_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_LIST_LIMIT = 100
_NUMBER_ATTEMPTS = 5


class RetestServiceError(Exception):
    """Base class for retest failures."""


class InvalidRetestReferenceError(RetestServiceError):
    """Malformed RETEST-### / REC-### / analysis id (400)."""


class RetestNotFoundError(RetestServiceError):
    """Unknown recommendation or retest (404)."""


class RetestConflictError(RetestServiceError):
    """Not completed, not eligible, unsupported spec, or already running (409)."""


class RetestIntegrityError(RetestServiceError):
    """The recommendation's reference chain is broken or crosses assessments (500)."""


class RetestPersistenceError(RetestServiceError):
    """MongoDB failed (500)."""


class RetestExecutionFailedError(RetestServiceError):
    """The retest was recorded with status ``failed`` (502)."""

    def __init__(self, retest: dict[str, Any]) -> None:
        self.retest = retest
        error = retest.get("error") or {}
        super().__init__(
            f"{retest.get('retest_id')} could not execute ({error.get('category', 'unknown')}): "
            f"{error.get('message', 'unknown error')}"
        )


def _to_object_id(assessment_id: str) -> ObjectId:
    if not ObjectId.is_valid(assessment_id):
        raise InvalidAssessmentIdError(f"{assessment_id!r} is not a valid assessment id.")
    return ObjectId(assessment_id)


def retest_reference(number: int) -> str:
    return f"RETEST-{number:03d}"


class RetestService:
    def __init__(
        self, db: AsyncDatabase, qa: QaService, security: SecurityService, settings: Settings
    ) -> None:
        self._qa = qa
        self._security = security
        self._settings = settings
        self._assessments = assessment_model.get_collection(db)
        self._recommendations = recommendation_model.get_collection(db)
        self._issues = issue_model.get_collection(db)
        self._evidence = evidence_model.get_collection(db)
        self._analyses = analysis_model.get_collection(db)
        self._retests = retest_model.get_collection(db)

    # --- execution --------------------------------------------------------------------

    async def execute(
        self, assessment_id: str, recommendation_id: str, ai_analysis_id: str | None = None
    ) -> dict[str, Any]:
        oid = _to_object_id(assessment_id)
        number_match = REC_ID_PATTERN.match(recommendation_id)
        if not number_match:
            raise InvalidRetestReferenceError(
                f"{recommendation_id!r} is not a valid recommendation reference (REC-###)."
            )
        if ai_analysis_id is not None and not ANALYSIS_ID_PATTERN.match(ai_analysis_id):
            raise InvalidRetestReferenceError(f"{ai_analysis_id!r} is not a valid analysis id.")

        assessment = await self._read(self._assessments, {"_id": oid})
        if assessment is None:
            raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
        if assessment.get("status") != AssessmentState.COMPLETED.value:
            raise RetestConflictError(
                f"Retests run only on a completed assessment; this one is {assessment.get('status')!r}."
            )

        recommendation = await self._recommendation(assessment_id, int(number_match.group(1)), ai_analysis_id)
        spec, evidence_docs, issue = await self._resolve_chain(assessment, recommendation)
        try:
            plan = plan_retest(spec, {eid: doc.get("category") for eid, doc in evidence_docs.items()})
        except RetestNotEligibleError as exc:
            raise RetestConflictError(f"{recommendation_id} is not eligible for a retest: {exc}") from exc

        retest = await self._reserve(assessment, recommendation, spec, issue, plan)
        started = time.perf_counter()
        try:
            fields = await self._run(assessment, spec, plan, evidence_docs)
        except Exception as exc:  # never leave a retest "running"
            logger.exception("Retest %s: unexpected failure", retest["retest_id"])
            fields = self._failure("internal_error", f"The retest could not complete ({type(exc).__name__}).")
        fields["completed_at"] = utc_now()
        fields["duration_ms"] = int((time.perf_counter() - started) * 1000)
        fields["updated_at"] = fields["completed_at"]
        try:
            await self._retests.update_one({"_id": retest["_id"]}, {"$set": fields})
        except PyMongoError as exc:
            raise RetestPersistenceError(f"Could not record the retest result: {type(exc).__name__}") from exc

        stored = retest_model.document_to_response({**retest, **fields})
        logger.info(
            "Retest %s %s: assessment=%s recommendation=%s verdict=%s",
            stored["retest_id"],
            stored["status"],
            assessment_id,
            recommendation_id,
            stored.get("verdict"),
        )
        if stored["status"] == "failed":
            raise RetestExecutionFailedError(stored)
        return stored

    async def _run(
        self, assessment: dict[str, Any], spec: RetestSpecification, plan, evidence_docs
    ) -> dict[str, Any]:
        target_id = str(assessment["target_id"])
        try:
            if plan.engine == "security":
                run = await self._security.run(target_id, components=plan.components, purpose="retest")
                new_evidence = [e.to_document() for e in normalize_security_run(run)]
            else:
                run = await self._qa.run(target_id, checks=plan.qa_checks, purpose="retest")
                new_evidence = [e.to_document() for e in normalize_qa_run(run)]
        except (QaServiceError, SecurityServiceError, TargetServiceError) as exc:
            return self._failure("engine_unavailable", f"The {plan.engine} engine could not run: {type(exc).__name__}.")

        source_runs = [{"engine": plan.engine, "run_id": str(run.get("id")), "status": run.get("status")}]
        problem = execution_problem(plan, run)
        if problem:
            return {
                **self._failure("execution_failed", problem),
                "source_runs": source_runs,
                "source_run_ids": [str(run.get("id"))],
            }

        result = evaluate(spec, plan, new_evidence)
        matched = [c for c in spec.checks] if result.verdict == "FAIL" else []
        return {
            "status": "completed",
            "verdict": result.verdict,
            "source_runs": source_runs,
            "source_run_ids": [str(run.get("id"))],
            "matched_evidence_ids": [c.evidence_id for c in matched],
            "matched_evidence_refs": [c.evidence_ref for c in matched],
            "observations": result.observations,
            "result_summary": {
                "engine": plan.engine,
                "results_evaluated": result.results_evaluated,
                "matching_results": len(result.observations) if result.verdict == "FAIL" else 0,
                "reason": result.reason,
            },
            "error": None,
        }

    @staticmethod
    def _failure(category: str, message: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "verdict": None,
            "matched_evidence_ids": [],
            "matched_evidence_refs": [],
            "observations": [],
            "result_summary": None,
            "error": {"category": category, "message": message[:500]},
        }

    # --- chain resolution (never trusts the client) ---------------------------------------

    async def _recommendation(self, assessment_id: str, number: int, ai_analysis_id: str | None) -> dict[str, Any]:
        if ai_analysis_id is None:
            newest = await self._read(
                self._recommendations, {"assessment_id": assessment_id}, sort=[("updated_at", -1), ("_id", -1)]
            )
            ai_analysis_id = newest.get("ai_analysis_id") if newest else None
        document = None
        if ai_analysis_id:
            document = await self._read(
                self._recommendations,
                {"assessment_id": assessment_id, "ai_analysis_id": ai_analysis_id, "recommendation_number": number},
            )
        if document is None:
            raise RetestNotFoundError(f"No recommendation REC-{number:03d} in assessment {assessment_id}.")
        return document

    async def _resolve_chain(self, assessment, recommendation):
        assessment_id = str(assessment["_id"])
        if recommendation.get("assessment_id") != assessment_id:
            raise RetestIntegrityError("The recommendation belongs to a different assessment.")
        try:
            spec = RetestSpecification.model_validate(recommendation.get("retest") or {})
        except ValidationError as exc:
            raise RetestConflictError(
                f"{recommendation.get('recommendation_id')} has no valid retest specification "
                f"({len(exc.errors())} problem(s)); it cannot be retested."
            ) from exc

        if spec.issue_id != recommendation.get("issue_id"):
            raise RetestIntegrityError("The retest specification names a different issue than its recommendation.")
        if spec.target_id != str(assessment.get("target_id")):
            raise RetestIntegrityError("The retest specification targets a different target than the assessment.")

        issue = await self._read(self._issues, {"assessment_id": assessment_id, "issue_id": spec.issue_id})
        if issue is None or issue.get("group_key") != spec.match_key:
            raise RetestIntegrityError(
                f"{spec.issue_id} does not exist in this assessment with the specification's match key."
            )

        analysis = await self._read(
            self._analyses,
            {"assessment_id": assessment_id, "analysis_id": recommendation.get("ai_analysis_id"), "status": "completed"},
        )
        if analysis is None:
            raise RetestIntegrityError("The recommendation's source AI analysis is not a completed analysis of this assessment.")

        ids = sorted({c.evidence_id for c in spec.checks})
        try:
            docs = await self._evidence.find({"evidence_id": {"$in": ids}}).to_list(length=None)
        except PyMongoError as exc:
            raise RetestPersistenceError(f"Could not read evidence: {type(exc).__name__}") from exc
        by_id = {str(d["evidence_id"]): d for d in docs}
        issue_evidence = set(issue.get("evidence_ids") or [])
        for check in spec.checks:
            doc = by_id.get(check.evidence_id)
            if doc is None or doc.get("assessment_id") != assessment_id:
                raise RetestIntegrityError(f"Check {check.evidence_ref} does not reference evidence of this assessment.")
            if check.evidence_id not in issue_evidence:
                raise RetestIntegrityError(f"Check {check.evidence_ref} is not evidence of {spec.issue_id}.")
            payload = doc.get("evidence_payload") or {}
            stored_rule = str(payload["rule_id"]) if payload.get("rule_id") else None
            if (
                check.source != doc.get("source")
                or check.title != doc.get("title")
                or check.finding_type != doc.get("finding_type")
                or check.rule_id != stored_rule
            ):
                raise RetestIntegrityError(f"Check {check.evidence_ref} does not match its stored evidence.")
        return spec, by_id, issue

    # --- numbering and the running lock ---------------------------------------------------

    async def _reserve(self, assessment, recommendation, spec: RetestSpecification, issue, plan) -> dict[str, Any]:
        assessment_id = str(assessment["_id"])
        recommendation_ref = str(recommendation["_id"])
        now = utc_now()
        stale_before = now - timedelta(seconds=self._settings.retest_stale_seconds)
        try:
            # A retest still "running" long after it started was abandoned
            # (e.g. the server stopped). Close it honestly; that frees the lock.
            await self._retests.update_many(
                {"recommendation_ref": recommendation_ref, "status": "running", "started_at": {"$lt": stale_before}},
                {
                    "$set": {
                        "status": "failed",
                        "verdict": None,
                        "completed_at": now,
                        "updated_at": now,
                        "error": {"category": "abandoned", "message": "The retest never finished (the server may have stopped)."},
                    }
                },
            )
        except PyMongoError as exc:
            raise RetestPersistenceError(f"Could not prepare the retest: {type(exc).__name__}") from exc

        base = {
            "assessment_id": assessment_id,
            "target_id": spec.target_id,
            "recommendation_id": recommendation.get("recommendation_id"),
            "recommendation_ref": recommendation_ref,
            "ai_analysis_id": recommendation.get("ai_analysis_id"),
            "issue_id": spec.issue_id,
            "correlation_group_id": issue.get("correlation_group_id"),
            "type": spec.retest_type,
            "scope": spec.scope,
            "target_component": spec.target_component,
            "match_key": spec.match_key,
            "pass_condition": spec.pass_condition,
            "checks": [c.model_dump() for c in spec.checks],
            "plan": plan.describe(),
            "status": "running",
            "verdict": None,
            "started_at": now,
            "completed_at": None,
            "duration_ms": None,
            "source_run_ids": [],
            "source_runs": [],
            "matched_evidence_ids": [],
            "matched_evidence_refs": [],
            "observations": [],
            "result_summary": None,
            "error": None,
            "retest_version": RETEST_VERSION,
            "created_at": now,
            "updated_at": now,
        }
        for _ in range(_NUMBER_ATTEMPTS):
            try:
                last = await self._read(self._retests, {"assessment_id": assessment_id}, sort=retest_model.LIST_SORT)
                number = int(last["retest_number"]) + 1 if last else 1
                document = {**base, "retest_id": retest_reference(number), "retest_number": number}
                result = await self._retests.insert_one(document)
                document["_id"] = result.inserted_id
                return document
            except DuplicateKeyError as exc:
                if retest_model.RUNNING_LOCK_INDEX_NAME in str(exc):
                    raise RetestConflictError(
                        f"A retest of {recommendation.get('recommendation_id')} is already running. Try again when it has finished."
                    ) from exc
                continue  # another retest took this number; take the next one
            except PyMongoError as exc:
                raise RetestPersistenceError(f"Could not record the retest: {type(exc).__name__}") from exc
        raise RetestPersistenceError("Could not allocate a retest number.")

    # --- reads ------------------------------------------------------------------------------

    async def _read(self, collection, query, sort=None):
        try:
            return await collection.find_one(query, sort=sort)
        except PyMongoError as exc:
            raise RetestPersistenceError(f"Could not read stored data: {type(exc).__name__}") from exc

    async def list_retests(
        self, assessment_id: str, recommendation_id: str | None = None, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[dict[str, Any]]:
        oid = _to_object_id(assessment_id)
        if await self._read(self._assessments, {"_id": oid}) is None:
            raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
        query: dict[str, Any] = {"assessment_id": assessment_id}
        if recommendation_id is not None:
            if not REC_ID_PATTERN.match(recommendation_id):
                raise InvalidRetestReferenceError(
                    f"{recommendation_id!r} is not a valid recommendation reference (REC-###)."
                )
            query["recommendation_id"] = recommendation_id
        try:
            documents = await self._retests.find(query).sort(retest_model.LIST_SORT).limit(limit).to_list(length=None)
        except PyMongoError as exc:
            raise RetestPersistenceError(f"Could not read retests: {type(exc).__name__}") from exc
        return [retest_model.document_to_response(d) for d in documents]

    async def get(self, assessment_id: str, retest_id: str) -> dict[str, Any]:
        oid = _to_object_id(assessment_id)
        match = RETEST_ID_PATTERN.match(retest_id)
        if await self._read(self._assessments, {"_id": oid}) is None:
            raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
        if not match:
            raise InvalidRetestReferenceError(f"{retest_id!r} is not a valid retest reference (RETEST-###).")
        document = await self._read(
            self._retests, {"assessment_id": assessment_id, "retest_number": int(match.group(1))}
        )
        if document is None:
            raise RetestNotFoundError(f"No retest {retest_id} in assessment {assessment_id}.")
        return retest_model.document_to_response(document)
