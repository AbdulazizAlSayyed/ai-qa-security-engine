"""Shared FastAPI dependencies.

Route handlers take these annotated types instead of importing settings or
the database module directly, which keeps them trivially overridable in
tests via ``app.dependency_overrides``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings, get_settings
from app.core.database import get_database
from app.engines.ai.gemini_provider import GeminiProvider
from app.engines.ai.openai_provider import OpenAIProvider
from app.engines.ai.provider import AIProvider, UnconfiguredProvider
from app.services.ai_analysis_service import AIAnalysisService
from app.services.assessment_service import AssessmentService
from app.services.correlation_service import CorrelationService
from app.services.dashboard_service import DashboardService
from app.services.issue_service import IssueService
from app.services.qa_service import QaService
from app.services.recommendation_service import RecommendationService
from app.services.report_service import ReportService
from app.services.retest_service import RetestService
from app.services.security_service import SecurityService
from app.services.target_service import TargetService


def get_db() -> AsyncDatabase:
    """Provide the application database to a route handler."""
    return get_database()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[AsyncDatabase, Depends(get_db)]


def get_target_service(db: DatabaseDep) -> TargetService:
    """Provide the target registry service to a route handler."""
    return TargetService(db)


TargetServiceDep = Annotated[TargetService, Depends(get_target_service)]


def get_qa_service(
    db: DatabaseDep, targets: TargetServiceDep, settings: SettingsDep
) -> QaService:
    """Provide the QA service, reusing the registry for target lookup."""
    return QaService(db=db, targets=targets, settings=settings)


QaServiceDep = Annotated[QaService, Depends(get_qa_service)]


def get_security_service(
    db: DatabaseDep, targets: TargetServiceDep, settings: SettingsDep
) -> SecurityService:
    """Provide the security service, reusing the registry for target lookup."""
    return SecurityService(db=db, targets=targets, settings=settings)


SecurityServiceDep = Annotated[SecurityService, Depends(get_security_service)]


def get_assessment_service(
    db: DatabaseDep,
    targets: TargetServiceDep,
    qa: QaServiceDep,
    security: SecurityServiceDep,
    settings: SettingsDep,
) -> AssessmentService:
    """Provide the orchestrator, composed from the services it sequences.

    It reuses QaService and SecurityService rather than the engines, so the
    raw runs they persist stay the untouched record of what each tool
    emitted.
    """
    return AssessmentService(
        db=db, targets=targets, qa=qa, security=security, settings=settings
    )


AssessmentServiceDep = Annotated[AssessmentService, Depends(get_assessment_service)]


def get_ai_provider(settings: SettingsDep) -> AIProvider:
    """The one place a concrete provider is chosen.

    Everything downstream depends on the ``AIProvider`` abstraction; tests
    override this dependency with a fake and never touch the network.
    """
    provider = settings.ai_provider.strip().lower()
    if provider == "openai":
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
            max_output_tokens=settings.ai_max_output_tokens,
        )
    if provider == "gemini":
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
            max_output_tokens=settings.ai_max_output_tokens,
        )
    return UnconfiguredProvider(
        provider,
        f"AI_PROVIDER={settings.ai_provider!r} is not supported. Use 'openai' or 'gemini'.",
    )


AIProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]


def get_ai_analysis_service(
    db: DatabaseDep, provider: AIProviderDep, settings: SettingsDep
) -> AIAnalysisService:
    """Analysis reads the database and talks to the provider - nothing else."""
    return AIAnalysisService(db=db, provider=provider, settings=settings)


AIAnalysisServiceDep = Annotated[AIAnalysisService, Depends(get_ai_analysis_service)]


def get_correlation_service(db: DatabaseDep, settings: SettingsDep) -> CorrelationService:
    """Correlation reads stored data only; it never needs an AI provider."""
    return CorrelationService(db=db, settings=settings)


CorrelationServiceDep = Annotated[CorrelationService, Depends(get_correlation_service)]


def get_issue_service(db: DatabaseDep) -> IssueService:
    return IssueService(db=db)


IssueServiceDep = Annotated[IssueService, Depends(get_issue_service)]


def get_dashboard_service(db: DatabaseDep) -> DashboardService:
    """Read-only aggregation over the stored collections."""
    return DashboardService(db=db)


DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]


def get_recommendation_service(
    db: DatabaseDep, analysis: AIAnalysisServiceDep, settings: SettingsDep
) -> RecommendationService:
    """Recommendations reach the model only through the existing AIAnalysisService."""
    return RecommendationService(db=db, analysis=analysis, settings=settings)


RecommendationServiceDep = Annotated[RecommendationService, Depends(get_recommendation_service)]


def get_retest_service(
    db: DatabaseDep, qa: QaServiceDep, security: SecurityServiceDep, settings: SettingsDep
) -> RetestService:
    """Retests re-run the existing engines through the existing services. No AI."""
    return RetestService(db=db, qa=qa, security=security, settings=settings)


RetestServiceDep = Annotated[RetestService, Depends(get_retest_service)]


def get_report_service(db: DatabaseDep, settings: SettingsDep) -> ReportService:
    """Reports read stored data and render it. No engine, no provider, no AI."""
    return ReportService(db=db, settings=settings)


ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
