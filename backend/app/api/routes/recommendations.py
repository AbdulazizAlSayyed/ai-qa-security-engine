"""Advisory recommendation endpoints (Phase 8).

Generation reads everything server-side (issues, their evidence, the latest
completed AI analysis) and calls the model only through AIAnalysisService.
Nothing here applies a fix, runs a command or triggers a retest.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query

from app.api.dependencies import RecommendationServiceDep
from app.schemas.recommendation import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendationsView,
)

router = APIRouter(prefix="/assessments", tags=["recommendations"])

_ANALYSIS_ID = Query(
    default=None,
    pattern=r"^[0-9a-f]{32}$",
    description="Show the set generated from this AI analysis instead of the newest set.",
)


@router.post(
    "/{assessment_id}/recommendations",
    response_model=RecommendationsView,
    summary="Generate advisory recommendations from the stored issues, evidence and AI analysis",
    responses={
        400: {"description": "Malformed assessment id."},
        404: {"description": "No such assessment."},
        409: {
            "description": "Not completed, no completed AI analysis, not correlated, correlation "
            "built from a different AI analysis, no issues, or a generation is in progress."
        },
        422: {"description": "A request body with fields was sent; this endpoint takes none."},
        500: {"description": "Recommendations could not be read or stored."},
        502: {"description": "The AI provider failed or its answer was rejected (recorded)."},
        503: {"description": "The AI provider is not configured (recorded)."},
    },
)
async def generate_recommendations(
    assessment_id: str,
    service: RecommendationServiceDep,
    payload: RecommendationRequest | None = Body(default=None),
) -> RecommendationsView:
    """Advisory only. Generating again from the same AI analysis updates the same
    recommendations (REC-### mirrors the issue number) instead of adding new ones."""
    return RecommendationsView(**await service.generate(assessment_id))


@router.get(
    "/{assessment_id}/recommendations",
    response_model=RecommendationsView,
    summary="Recommendations of an assessment (newest set, or the set of one AI analysis)",
    responses={400: {"description": "Malformed id."}, 404: {"description": "No such assessment."}},
)
async def list_recommendations(
    assessment_id: str,
    service: RecommendationServiceDep,
    ai_analysis_id: str | None = _ANALYSIS_ID,
) -> RecommendationsView:
    return RecommendationsView(**await service.view(assessment_id, ai_analysis_id))


@router.get(
    "/{assessment_id}/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
    summary="One recommendation with its retest specification",
    responses={
        400: {"description": "Malformed assessment id or recommendation reference."},
        404: {"description": "No such assessment or recommendation."},
    },
)
async def get_recommendation(
    assessment_id: str,
    recommendation_id: str,
    service: RecommendationServiceDep,
    ai_analysis_id: str | None = _ANALYSIS_ID,
) -> RecommendationResponse:
    return RecommendationResponse(**await service.get(assessment_id, recommendation_id, ai_analysis_id))
