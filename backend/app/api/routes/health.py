"""Health endpoints.

``/health`` is a *dependency* check: it proves the API can actually reach
MongoDB right now, and returns 503 when it cannot. ``/health/live`` is a
liveness check that only proves the process is up.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response, status

from app.api.dependencies import SettingsDep
from app.core import database
from app.schemas.health import DatabaseHealth, HealthResponse, LivenessResponse

router = APIRouter(tags=["health"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health including MongoDB connectivity",
    responses={
        200: {"description": "API is up and MongoDB responded to a ping."},
        503: {
            "model": HealthResponse,
            "description": "API is up but MongoDB is unreachable.",
        },
    },
)
async def health(response: Response, settings: SettingsDep) -> HealthResponse:
    """Ping MongoDB and report the result.

    The status code reflects the dependency, not the process: a reachable
    API with a dead database is a degraded service, and monitoring should
    see that as a failure rather than a 200.
    """
    db_state = await database.ping()
    db_health = DatabaseHealth(**db_state)

    connected = db_health.status == "connected"
    if not connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if connected else "degraded",
        service=settings.project_name,
        version=settings.api_version,
        environment=settings.environment,
        timestamp=_now(),
        database=db_health,
    )


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Process liveness (does not touch MongoDB)",
)
async def liveness(settings: SettingsDep) -> LivenessResponse:
    """Return 200 as long as the API process can serve a request."""
    return LivenessResponse(
        status="alive",
        service=settings.project_name,
        timestamp=_now(),
    )
