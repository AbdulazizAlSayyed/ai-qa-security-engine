"""Dashboard aggregation endpoint (Phase 7). Read-only.

One response with everything the dashboard page shows, computed from the
stored assessments, issues and targets. Starting an assessment from the
dashboard uses the existing ``POST /assessments``; there is no second path.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.dependencies import DashboardServiceDep
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_TREND_DAYS,
    MAX_HISTORY_LIMIT,
    MAX_TREND_DAYS,
)

router = APIRouter(tags=["dashboard"])


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Aggregated assessment, QA, security and issue overview with history and trends",
    responses={
        422: {"description": "history_limit or trend_days out of range."},
        500: {"description": "The aggregation could not be read from MongoDB."},
    },
)
async def get_dashboard(
    service: DashboardServiceDep,
    history_limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
    trend_days: int = Query(DEFAULT_TREND_DAYS, ge=1, le=MAX_TREND_DAYS),
) -> DashboardResponse:
    return DashboardResponse(
        **await service.overview(history_limit=history_limit, trend_days=trend_days)
    )
