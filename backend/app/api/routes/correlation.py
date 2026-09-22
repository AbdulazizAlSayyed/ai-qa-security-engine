"""Correlation & prioritization endpoints (Phase 6).

The operation is explicit and idempotent: it reads the stored evidence (and
the latest completed AI analysis, when one exists) of one completed
assessment and upserts its correlation groups and prioritized issues. It
takes no input and calls no AI provider.
"""

from __future__ import annotations

from fastapi import APIRouter, Body

from app.api.dependencies import CorrelationServiceDep
from app.schemas.correlation import (
    CorrelationGroupResponse,
    CorrelationRequest,
    CorrelationRunResponse,
)

router = APIRouter(prefix="/assessments", tags=["correlation"])

_BAD_ID = {"description": "The id is not a well-formed ObjectId."}


@router.post(
    "/{assessment_id}/correlation",
    response_model=CorrelationRunResponse,
    summary="Correlate and prioritize an assessment's evidence into issues",
    responses={
        400: _BAD_ID,
        404: {"description": "No such assessment."},
        409: {"description": "The assessment is not completed, or a run is in progress."},
        422: {"description": "A request body with fields was sent; this endpoint takes none."},
        500: {"description": "Derived data could not be read or written, or failed an integrity check."},
    },
)
async def run_correlation(
    assessment_id: str,
    service: CorrelationServiceDep,
    payload: CorrelationRequest | None = Body(default=None),
) -> CorrelationRunResponse:
    """200 with the prioritized issues. Running it again updates the same
    groups and issues instead of creating new ones."""
    return CorrelationRunResponse(**await service.process(assessment_id))


@router.get(
    "/{assessment_id}/correlation-groups",
    response_model=list[CorrelationGroupResponse],
    summary="Correlation groups of an assessment, in CG-### order",
    responses={400: _BAD_ID, 404: {"description": "No such assessment."}},
)
async def list_correlation_groups(
    assessment_id: str, service: CorrelationServiceDep
) -> list[CorrelationGroupResponse]:
    return [CorrelationGroupResponse(**g) for g in await service.list_groups(assessment_id)]
