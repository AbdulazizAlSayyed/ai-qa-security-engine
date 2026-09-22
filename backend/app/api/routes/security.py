"""Security engine endpoints.

Thin, like the QA routes. Note there is intentionally no endpoint that takes
a URL: a caller identifies a *registered target*, and the engine reads the
URLs from the registry. That is what keeps this platform pointed only at
applications someone deliberately authorised it to scan.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.dependencies import SecurityServiceDep
from app.schemas.security import SecurityRunRequest, SecurityRunResponse
from app.services.security_service import DEFAULT_RUN_LIMIT

router = APIRouter(prefix="/security", tags=["security"])

_BAD_ID = {"description": "The id is not a well-formed ObjectId."}
_NOT_FOUND = {"description": "No such security run."}
_NOT_SCANNABLE = {
    "description": "The target is disabled, not a web target, or scanning is switched off."
}


@router.post(
    "/runs",
    response_model=SecurityRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run a security assessment against a registered target",
    responses={
        400: _BAD_ID,
        404: {"description": "No such target."},
        409: _NOT_SCANNABLE,
    },
)
async def create_security_run(
    payload: SecurityRunRequest, service: SecurityServiceDep
) -> SecurityRunResponse:
    """Scan a registered target and store the result.

    Returns 201 whenever an assessment executed and was recorded, however
    many vulnerabilities it found. A finding is evidence, not an HTTP error.
    """
    return SecurityRunResponse(**await service.run(payload.target_id))


@router.get(
    "/runs",
    response_model=list[SecurityRunResponse],
    summary="List security runs, newest first",
)
async def list_security_runs(
    service: SecurityServiceDep,
    limit: int = Query(
        DEFAULT_RUN_LIMIT,
        ge=1,
        le=200,
        description="Maximum number of runs to return.",
    ),
) -> list[SecurityRunResponse]:
    """Recent security runs across all targets."""
    return [SecurityRunResponse(**run) for run in await service.list_runs(limit=limit)]


@router.get(
    "/runs/{run_id}",
    response_model=SecurityRunResponse,
    summary="Get one security run",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_security_run(
    run_id: str, service: SecurityServiceDep
) -> SecurityRunResponse:
    """Full detail for a single security run, including every finding."""
    return SecurityRunResponse(**await service.get_run(run_id))
