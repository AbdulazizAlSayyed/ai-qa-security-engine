"""Retest endpoints (Phase 9).

The only input is which stored recommendation to retest. The server loads
its retest specification and runs exactly that scope through the existing
QA / security engine. Nothing is fixed, changed or re-scored.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, status

from app.api.dependencies import RetestServiceDep
from app.schemas.retest import RetestRequest, RetestResponse
from app.services.retest_service import DEFAULT_LIST_LIMIT

router = APIRouter(prefix="/assessments", tags=["retests"])


@router.post(
    "/{assessment_id}/recommendations/{recommendation_id}/retest",
    response_model=RetestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute the stored retest specification of a recommendation",
    responses={
        400: {"description": "Malformed assessment id, recommendation reference or analysis id."},
        404: {"description": "No such assessment or recommendation."},
        409: {
            "description": "Assessment not completed, specification not eligible or unsupported, "
            "or a retest of this recommendation is already running."
        },
        422: {"description": "A request body with fields was sent; this endpoint takes none."},
        500: {"description": "Broken or cross-assessment reference chain, or persistence failure."},
        502: {"description": "The engine could not execute; recorded as a failed retest (no verdict)."},
    },
)
async def run_retest(
    assessment_id: str,
    recommendation_id: str,
    service: RetestServiceDep,
    ai_analysis_id: str | None = Query(
        default=None, description="Recommendation set to use; defaults to the newest set."
    ),
    payload: RetestRequest | None = Body(default=None),
) -> RetestResponse:
    """201 with a completed retest and its PASS / FAIL verdict. Every call is a
    new RETEST-### record; earlier retests are never changed."""
    return RetestResponse(**await service.execute(assessment_id, recommendation_id, ai_analysis_id))


@router.get(
    "/{assessment_id}/retests",
    response_model=list[RetestResponse],
    summary="Retest history of an assessment (or of one recommendation), newest first",
    responses={400: {"description": "Malformed id."}, 404: {"description": "No such assessment."}},
)
async def list_retests(
    assessment_id: str,
    service: RetestServiceDep,
    recommendation_id: str | None = Query(default=None),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=500),
) -> list[RetestResponse]:
    return [
        RetestResponse(**item)
        for item in await service.list_retests(assessment_id, recommendation_id, limit)
    ]


@router.get(
    "/{assessment_id}/retests/{retest_id}",
    response_model=RetestResponse,
    summary="One retest execution",
    responses={
        400: {"description": "Malformed id or RETEST-### reference."},
        404: {"description": "No such assessment or retest."},
    },
)
async def get_retest(assessment_id: str, retest_id: str, service: RetestServiceDep) -> RetestResponse:
    return RetestResponse(**await service.get(assessment_id, retest_id))
