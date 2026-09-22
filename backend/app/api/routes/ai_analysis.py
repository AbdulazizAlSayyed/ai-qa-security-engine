"""Evidence-grounded AI analysis endpoints.

Analysis is always tied to an existing assessment: the backend loads that
assessment's normalized evidence itself. There is no endpoint that accepts
evidence, a URL or a free-form prompt from the client.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, status

from app.api.dependencies import AIAnalysisServiceDep
from app.schemas.ai_analysis import AIAnalysisRequest, AIAnalysisResponse, AIAnalysisView
from app.services.ai_analysis_service import DEFAULT_HISTORY_LIMIT

router = APIRouter(prefix="/assessments", tags=["ai-analysis"])

_BAD_ID = {"description": "The id is not a well-formed ObjectId."}


@router.post(
    "/{assessment_id}/ai-analysis",
    response_model=AIAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyse an assessment's normalized evidence with the configured AI provider",
    responses={
        400: _BAD_ID,
        404: {"description": "No such assessment, or it has no evidence."},
        409: {"description": "The assessment is not completed, or is already being analysed."},
        422: {"description": "A request body was sent; this endpoint takes none."},
        500: {"description": "The analysis could not be recorded."},
        502: {"description": "The AI provider failed or its answer was rejected (recorded)."},
        503: {"description": "The AI provider is not configured (recorded)."},
    },
)
async def create_ai_analysis(
    assessment_id: str,
    service: AIAnalysisServiceDep,
    payload: AIAnalysisRequest | None = Body(default=None),
) -> AIAnalysisResponse:
    """Run one analysis and store it in ``ai_analysis_logs``.

    201 means the analysis completed and passed every validation check. A
    failed analysis is still recorded; the error response names its id.
    """
    return AIAnalysisResponse(**await service.analyze(assessment_id))


@router.get(
    "/{assessment_id}/ai-analysis",
    response_model=AIAnalysisView,
    summary="Latest AI analysis status and result for an assessment",
    responses={400: _BAD_ID, 404: {"description": "No such assessment."}},
)
async def get_ai_analysis(assessment_id: str, service: AIAnalysisServiceDep) -> AIAnalysisView:
    """``status`` is ``not_analyzed`` until the first attempt exists."""
    return AIAnalysisView(**await service.latest(assessment_id))


@router.get(
    "/{assessment_id}/ai-analysis/history",
    response_model=list[AIAnalysisResponse],
    summary="Every AI analysis attempt for an assessment, newest first",
    responses={400: _BAD_ID, 404: {"description": "No such assessment."}},
)
async def get_ai_analysis_history(
    assessment_id: str,
    service: AIAnalysisServiceDep,
    limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=100),
) -> list[AIAnalysisResponse]:
    return [
        AIAnalysisResponse(**item) for item in await service.history(assessment_id, limit=limit)
    ]
