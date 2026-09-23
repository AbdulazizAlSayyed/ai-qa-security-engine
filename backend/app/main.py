"""FastAPI application entry point.

Run it with::

    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

from the ``backend/`` directory, with the virtualenv active.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.api.routes import ai_analysis as ai_analysis_routes
from app.api.routes import assessments as assessment_routes
from app.api.routes import correlation as correlation_routes
from app.api.routes import dashboard as dashboard_routes
from app.api.routes import discoveries as discovery_routes
from app.api.routes import health as health_routes
from app.api.routes import issues as issue_routes
from app.api.routes import qa as qa_routes
from app.api.routes import recommendations as recommendation_routes
from app.api.routes import reports as report_routes
from app.api.routes import requirements as requirement_routes
from app.api.routes import retests as retest_routes
from app.api.routes import security as security_routes
from app.api.routes import targets as target_routes
from app.api.routes import test_accounts as test_account_routes
from app.core.config import get_settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_database
from app.core.logging import configure_logging, get_logger
from app.models.ai_analysis import ensure_indexes as ensure_ai_analysis_indexes
from app.models.application_map import ensure_indexes as ensure_application_map_indexes
from app.models.assessment import ensure_indexes as ensure_assessment_indexes
from app.models.correlation_group import ensure_indexes as ensure_correlation_group_indexes
from app.models.evidence import ensure_indexes as ensure_evidence_indexes
from app.models.issue import ensure_indexes as ensure_issue_indexes
from app.models.qa_run import ensure_indexes as ensure_qa_indexes
from app.models.recommendation import ensure_indexes as ensure_recommendation_indexes
from app.models.report import ensure_indexes as ensure_report_indexes
from app.models.requirement import ensure_indexes as ensure_requirement_indexes
from app.models.retest import ensure_indexes as ensure_retest_indexes
from app.models.security_run import ensure_indexes as ensure_security_indexes
from app.models.target import ensure_indexes as ensure_target_indexes
from app.models.test_account import ensure_indexes as ensure_test_account_indexes
from app.services.ai_analysis_service import (
    AIAnalysisFailedError,
    AIAnalysisPersistenceError,
    AssessmentNotAnalyzableError,
    NoEvidenceError,
)
from app.services.correlation_service import (
    AssessmentNotProcessableError,
    CorrelationPersistenceError,
    CorrelationProcessingError,
)
from app.services.dashboard_service import DashboardPersistenceError
from app.services.discovery_service import (
    DiscoveryNotFoundError,
    DiscoveryPersistenceError,
    InvalidDiscoveryIdError,
    TargetNotDiscoverableError,
)
from app.services.issue_service import InvalidIssueIdError, IssueNotFoundError
from app.services.report_service import (
    InvalidReportReferenceError,
    ReportArtifactIntegrityError,
    ReportGenerationFailedError,
    ReportNotFoundError,
    ReportPersistenceError,
    ReportPreconditionError,
    ReportTraceabilityError,
)
from app.services.requirement_service import (
    InvalidOpenApiDocumentError,
    InvalidRequirementIdError,
    RequirementExtractionError,
    RequirementNotFoundError,
    RequirementPersistenceError,
)
from app.services.retest_service import (
    InvalidRetestReferenceError,
    RetestConflictError,
    RetestExecutionFailedError,
    RetestIntegrityError,
    RetestNotFoundError,
    RetestPersistenceError,
)
from app.services.recommendation_service import (
    InvalidRecommendationIdError,
    RecommendationGenerationFailedError,
    RecommendationNotFoundError,
    RecommendationPersistenceError,
    RecommendationPrerequisiteError,
)
from app.services.assessment_service import (
    AssessmentNotFoundError,
    AssessmentOrchestrationError,
    AssessmentPersistenceError,
    InvalidAssessmentIdError,
    TargetNotAssessableError,
)
from app.services.qa_service import (
    InvalidQaRunIdError,
    QaPersistenceError,
    QaRunNotFoundError,
    TargetNotRunnableError,
)
from app.services.security_service import (
    InvalidSecurityRunIdError,
    SecurityPersistenceError,
    SecurityRunNotFoundError,
    TargetNotScannableError,
)
from app.services.target_service import (
    DuplicateTargetError,
    InvalidTargetIdError,
    InvalidTargetProfileError,
    TargetHasRequirementsError,
    TargetHasTestAccountsError,
    TargetNotFoundError,
)
from app.services.test_account_service import (
    DuplicateTestAccountError,
    InvalidTestAccountIdError,
    TestAccountNotFoundError,
)

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

DESCRIPTION = """
Platform that runs real functional QA and real security tests against a
registered target application, normalises the evidence those tools produce,
and uses an LLM to explain, prioritise and recommend fixes for what the
evidence actually shows.

The AI never invents results. Every finding references evidence produced by
a tool that genuinely executed.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the MongoDB client and workspace directories for the process."""
    logger.info(
        "Starting %s v%s (environment=%s)",
        settings.project_name,
        settings.api_version,
        settings.environment,
    )
    await connect_to_mongo()

    settings.qa_workspace_root.mkdir(parents=True, exist_ok=True)
    settings.reports_root.mkdir(parents=True, exist_ok=True)
    logger.info("QA workspace root: %s", settings.qa_workspace_root)
    logger.info("CORS allow-list: %s", ", ".join(settings.cors_origins))

    # Index creation needs a reachable server. A dead MongoDB must not stop
    # the API from starting - /health exists to report that condition.
    try:
        database = get_database()
        await ensure_target_indexes(database)
        await ensure_test_account_indexes(database)
        await ensure_requirement_indexes(database)
        await ensure_application_map_indexes(database)
        await ensure_qa_indexes(database)
        await ensure_security_indexes(database)
        await ensure_assessment_indexes(database)
        await ensure_evidence_indexes(database)
        await ensure_ai_analysis_indexes(database)
        await ensure_correlation_group_indexes(database)
        await ensure_issue_indexes(database)
        await ensure_recommendation_indexes(database)
        await ensure_retest_indexes(database)
        await ensure_report_indexes(database)
        logger.info(
            "Target, test account, requirement, application map, QA, security, "
            "assessment, evidence, AI analysis, correlation group, issue, "
            "recommendation, retest and report indexes ensured"
        )
    except PyMongoError as exc:
        logger.warning("Could not ensure indexes (is MongoDB running?): %s", exc)

    yield

    await close_mongo_connection()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.project_name,
    version=settings.api_version,
    description=DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_routes.router)
app.include_router(target_routes.router)
app.include_router(test_account_routes.router)
app.include_router(requirement_routes.router)
app.include_router(discovery_routes.router)
app.include_router(qa_routes.router)
app.include_router(security_routes.router)
app.include_router(assessment_routes.router)
app.include_router(ai_analysis_routes.router)
app.include_router(correlation_routes.router)
app.include_router(issue_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(recommendation_routes.router)
app.include_router(retest_routes.router)
app.include_router(report_routes.router)


# --- Service error translation ---------------------------------------
# The service layer raises domain errors, not HTTPException, so it stays
# usable from non-HTTP callers (the orchestrator will read targets later).
# This is the single place that maps those errors onto status codes.


def _problem(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


#: Field names whose value is a credential. A validation error about one of
#: these must not quote what was sent.
_CREDENTIAL_FIELD_NAMES = frozenset(
    {"password", "passwd", "secret", "token", "cookie", "credential", "api_key", "apikey"}
)
_REDACTED = "<redacted>"


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(_: Request, exc: RequestValidationError):
    """FastAPI's 422, with credential values stripped out of it.

    The default handler echoes the rejected input back so a caller can see
    what was wrong with it. That is genuinely useful, and wrong for exactly
    one case: a password sent to a field that refuses passwords would be
    quoted verbatim in the error body.

    Rejecting the request is not enough on its own, because the platform
    promises a credential never appears in a response. So the value is
    replaced wherever the field it belongs to is credential-shaped, and left
    alone everywhere else - a rejected URL or enum still says what it got.
    """
    errors: list[dict[str, Any]] = []
    for error in exc.errors():
        item = dict(error)
        location = [str(part).lower() for part in item.get("loc", ())]
        message = str(item.get("msg", "")).lower()
        # Either the field is one that holds a credential, or the validator
        # said the value looked like one - a password pasted into a notes
        # field is still a password.
        credential_shaped = any(
            part in _CREDENTIAL_FIELD_NAMES for part in location
        ) or any(word in message for word in ("credential", "password"))
        if "input" in item and credential_shaped:
            item["input"] = _REDACTED
        # Pydantic can attach the original exception, which may repeat the value.
        item.pop("ctx", None)
        item.pop("url", None)
        errors.append(item)
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(InvalidTargetIdError)
async def _handle_invalid_target_id(_: Request, exc: InvalidTargetIdError):
    return _problem(400, str(exc))


@app.exception_handler(TargetNotFoundError)
async def _handle_target_not_found(_: Request, exc: TargetNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(DuplicateTargetError)
async def _handle_duplicate_target(_: Request, exc: DuplicateTargetError):
    return _problem(409, str(exc))


@app.exception_handler(InvalidTargetProfileError)
async def _handle_invalid_target_profile(_: Request, exc: InvalidTargetProfileError):
    # The request was well formed and the target exists; the profile the
    # patch would produce is what is refused. Same status code a create with
    # the same combination gets from pydantic, so the two agree.
    return _problem(422, str(exc))


@app.exception_handler(TargetHasTestAccountsError)
async def _handle_target_has_accounts(_: Request, exc: TargetHasTestAccountsError):
    # Nothing was deleted. The registry's state is what forbids it.
    return _problem(409, str(exc))


@app.exception_handler(InvalidTestAccountIdError)
async def _handle_invalid_test_account_id(_: Request, exc: InvalidTestAccountIdError):
    return _problem(400, str(exc))


@app.exception_handler(TestAccountNotFoundError)
async def _handle_test_account_not_found(_: Request, exc: TestAccountNotFoundError):
    # Also the answer when the account exists but belongs to another target:
    # from this target's perspective it is not there, and saying so would
    # confirm an identity the caller did not address.
    return _problem(404, str(exc))


@app.exception_handler(DuplicateTestAccountError)
async def _handle_duplicate_test_account(_: Request, exc: DuplicateTestAccountError):
    return _problem(409, str(exc))


@app.exception_handler(TargetHasRequirementsError)
async def _handle_target_has_requirements(_: Request, exc: TargetHasRequirementsError):
    # Nothing was deleted. Same reasoning as the test account guard: the
    # registry's state is what forbids it, and saying so is better than
    # cascading away statements someone wrote.
    return _problem(409, str(exc))


@app.exception_handler(InvalidRequirementIdError)
async def _handle_invalid_requirement_id(_: Request, exc: InvalidRequirementIdError):
    return _problem(400, str(exc))


@app.exception_handler(RequirementNotFoundError)
async def _handle_requirement_not_found(_: Request, exc: RequirementNotFoundError):
    # Also the answer when the requirement exists but belongs to another
    # target: from this target's perspective it is not there.
    return _problem(404, str(exc))


@app.exception_handler(InvalidOpenApiDocumentError)
async def _handle_invalid_openapi_document(_: Request, exc: InvalidOpenApiDocumentError):
    # The request was well formed; the document in it is what cannot be read.
    return _problem(422, str(exc))


@app.exception_handler(RequirementExtractionError)
async def _handle_requirement_extraction_failed(_: Request, exc: RequirementExtractionError):
    # Same contract as Phase 5 and Phase 8: 503 when no provider is
    # configured, 502 when the provider failed or its answer was rejected.
    # Nothing was written to the registry in either case.
    return _problem(503 if exc.category == "configuration" else 502, str(exc))


@app.exception_handler(RequirementPersistenceError)
async def _handle_requirement_persistence(_: Request, exc: RequirementPersistenceError):
    logger.error("Requirement persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(InvalidDiscoveryIdError)
async def _handle_invalid_discovery_id(_: Request, exc: InvalidDiscoveryIdError):
    return _problem(400, str(exc))


@app.exception_handler(DiscoveryNotFoundError)
async def _handle_discovery_not_found(_: Request, exc: DiscoveryNotFoundError):
    # Also the answer when the run exists on another target: from this
    # target's perspective it is not there.
    return _problem(404, str(exc))


@app.exception_handler(TargetNotDiscoverableError)
async def _handle_target_not_discoverable(_: Request, exc: TargetNotDiscoverableError):
    # The target exists and the request was well formed; the registry's
    # current state is what forbids the crawl.
    return _problem(409, str(exc))


@app.exception_handler(DiscoveryPersistenceError)
async def _handle_discovery_persistence(_: Request, exc: DiscoveryPersistenceError):
    # The crawl really happened; losing it silently would be worse than
    # telling the caller the platform failed.
    logger.error("Discovery persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(InvalidQaRunIdError)
async def _handle_invalid_qa_run_id(_: Request, exc: InvalidQaRunIdError):
    return _problem(400, str(exc))


@app.exception_handler(QaRunNotFoundError)
async def _handle_qa_run_not_found(_: Request, exc: QaRunNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(TargetNotRunnableError)
async def _handle_target_not_runnable(_: Request, exc: TargetNotRunnableError):
    # The target exists and the request was well formed; the registry's
    # current state is what forbids the run.
    return _problem(409, str(exc))


@app.exception_handler(QaPersistenceError)
async def _handle_qa_persistence_error(_: Request, exc: QaPersistenceError):
    # The platform failed, not the target under test.
    logger.error("QA persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(InvalidSecurityRunIdError)
async def _handle_invalid_security_run_id(_: Request, exc: InvalidSecurityRunIdError):
    return _problem(400, str(exc))


@app.exception_handler(SecurityRunNotFoundError)
async def _handle_security_run_not_found(_: Request, exc: SecurityRunNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(TargetNotScannableError)
async def _handle_target_not_scannable(_: Request, exc: TargetNotScannableError):
    # The target exists and the request was well formed; the registry's
    # state (or configuration) is what forbids the scan.
    return _problem(409, str(exc))


@app.exception_handler(SecurityPersistenceError)
async def _handle_security_persistence_error(_: Request, exc: SecurityPersistenceError):
    logger.error("Security persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(InvalidAssessmentIdError)
async def _handle_invalid_assessment_id(_: Request, exc: InvalidAssessmentIdError):
    return _problem(400, str(exc))


@app.exception_handler(AssessmentNotFoundError)
async def _handle_assessment_not_found(_: Request, exc: AssessmentNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(TargetNotAssessableError)
async def _handle_target_not_assessable(_: Request, exc: TargetNotAssessableError):
    return _problem(409, str(exc))


@app.exception_handler(AssessmentPersistenceError)
async def _handle_assessment_persistence_error(
    _: Request, exc: AssessmentPersistenceError
):
    logger.error("Assessment persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(AssessmentOrchestrationError)
async def _handle_assessment_orchestration_error(
    _: Request, exc: AssessmentOrchestrationError
):
    # A bug in the pipeline itself - never a finding about the target.
    logger.error("Assessment orchestration failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(AssessmentNotAnalyzableError)
async def _handle_not_analyzable(_: Request, exc: AssessmentNotAnalyzableError):
    return _problem(409, str(exc))


@app.exception_handler(NoEvidenceError)
async def _handle_no_evidence(_: Request, exc: NoEvidenceError):
    return _problem(404, str(exc))


@app.exception_handler(AIAnalysisFailedError)
async def _handle_analysis_failed(_: Request, exc: AIAnalysisFailedError):
    # Recorded as a failed analysis already. The assessment is untouched.
    # 503 when the provider simply is not configured, 502 when the provider
    # failed or its answer was rejected by validation.
    status_code = 503 if exc.category == "configuration" else 502
    return _problem(status_code, str(exc))


@app.exception_handler(AIAnalysisPersistenceError)
async def _handle_analysis_persistence(_: Request, exc: AIAnalysisPersistenceError):
    logger.error("AI analysis persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(AssessmentNotProcessableError)
async def _handle_not_processable(_: Request, exc: AssessmentNotProcessableError):
    return _problem(409, str(exc))


@app.exception_handler(InvalidIssueIdError)
async def _handle_invalid_issue_id(_: Request, exc: InvalidIssueIdError):
    return _problem(400, str(exc))


@app.exception_handler(IssueNotFoundError)
async def _handle_issue_not_found(_: Request, exc: IssueNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(CorrelationProcessingError)
async def _handle_correlation_processing(_: Request, exc: CorrelationProcessingError):
    # Stored data broke an integrity rule; recorded on the assessment.
    logger.error("Correlation integrity failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(CorrelationPersistenceError)
async def _handle_correlation_persistence(_: Request, exc: CorrelationPersistenceError):
    logger.error("Correlation persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(DashboardPersistenceError)
async def _handle_dashboard_persistence(_: Request, exc: DashboardPersistenceError):
    logger.error("Dashboard aggregation failure: %s", exc)
    return _problem(500, "Dashboard data could not be read. Check that MongoDB is running.")


@app.exception_handler(RecommendationPrerequisiteError)
async def _handle_recommendation_prerequisite(_: Request, exc: RecommendationPrerequisiteError):
    return _problem(409, str(exc))


@app.exception_handler(InvalidRecommendationIdError)
async def _handle_invalid_recommendation_id(_: Request, exc: InvalidRecommendationIdError):
    return _problem(400, str(exc))


@app.exception_handler(RecommendationNotFoundError)
async def _handle_recommendation_not_found(_: Request, exc: RecommendationNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(RecommendationGenerationFailedError)
async def _handle_recommendation_failed(_: Request, exc: RecommendationGenerationFailedError):
    # Same contract as Phase 5: recorded, then 503 when unconfigured, else 502.
    return _problem(503 if exc.category == "configuration" else 502, str(exc))


@app.exception_handler(RecommendationPersistenceError)
async def _handle_recommendation_persistence(_: Request, exc: RecommendationPersistenceError):
    logger.error("Recommendation persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(InvalidRetestReferenceError)
async def _handle_invalid_retest_reference(_: Request, exc: InvalidRetestReferenceError):
    return _problem(400, str(exc))


@app.exception_handler(RetestNotFoundError)
async def _handle_retest_not_found(_: Request, exc: RetestNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(RetestConflictError)
async def _handle_retest_conflict(_: Request, exc: RetestConflictError):
    return _problem(409, str(exc))


@app.exception_handler(RetestExecutionFailedError)
async def _handle_retest_failed(_: Request, exc: RetestExecutionFailedError):
    # Recorded as a failed retest (status failed, no verdict) - like Phase 5's 502.
    return _problem(502, str(exc))


@app.exception_handler(RetestIntegrityError)
async def _handle_retest_integrity(_: Request, exc: RetestIntegrityError):
    logger.error("Retest integrity failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(RetestPersistenceError)
async def _handle_retest_persistence(_: Request, exc: RetestPersistenceError):
    logger.error("Retest persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(InvalidReportReferenceError)
async def _handle_invalid_report_reference(_: Request, exc: InvalidReportReferenceError):
    return _problem(400, str(exc))


@app.exception_handler(ReportNotFoundError)
async def _handle_report_not_found(_: Request, exc: ReportNotFoundError):
    return _problem(404, str(exc))


@app.exception_handler(ReportPreconditionError)
async def _handle_report_precondition(_: Request, exc: ReportPreconditionError):
    return _problem(409, str(exc))


@app.exception_handler(ReportTraceabilityError)
async def _handle_report_traceability(_: Request, exc: ReportTraceabilityError):
    # Stored data breaks a reference: nothing is repaired, the attempt is recorded
    # as a failed report and no misleading report is rendered.
    logger.warning("Report traceability failure: %s", exc)
    return _problem(409, str(exc))


@app.exception_handler(ReportGenerationFailedError)
async def _handle_report_failed(_: Request, exc: ReportGenerationFailedError):
    logger.error("Report generation failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(ReportArtifactIntegrityError)
async def _handle_report_artifact(_: Request, exc: ReportArtifactIntegrityError):
    logger.error("Report artifact integrity failure: %s", exc)
    return _problem(500, str(exc))


@app.exception_handler(ReportPersistenceError)
async def _handle_report_persistence(_: Request, exc: ReportPersistenceError):
    logger.error("Report persistence failure: %s", exc)
    return _problem(500, str(exc))


@app.get("/", tags=["meta"], summary="Service metadata")
async def root() -> dict[str, str]:
    """Identify the service and point at its documentation."""
    return {
        "service": settings.project_name,
        "version": settings.api_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health",
    }
