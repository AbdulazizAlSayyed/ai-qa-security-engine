"""QA engine endpoints.

Thin, like the target routes: validate, delegate, shape the response.
Service errors are translated into status codes by the handlers registered
in ``app.main``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.dependencies import QaServiceDep
from app.schemas.qa import QaRunRequest, QaRunResponse
from app.services.qa_service import DEFAULT_RUN_LIMIT

router = APIRouter(prefix="/qa", tags=["qa"])

_BAD_ID = {"description": "The id is not a well-formed ObjectId."}
_NOT_FOUND = {"description": "No such QA run."}
_NOT_RUNNABLE = {"description": "The target is disabled or not a web target."}


@router.post(
    "/runs",
    response_model=QaRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run the QA smoke suite against a registered target",
    responses={
        400: _BAD_ID,
        404: {"description": "No such target."},
        409: _NOT_RUNNABLE,
    },
)
async def create_qa_run(payload: QaRunRequest, service: QaServiceDep) -> QaRunResponse:
    """Execute the smoke suite and store the result.

    Returns 201 whenever a run was executed and recorded -- including when
    its status is ``failed`` or ``error``. Those describe the target and the
    engine respectively, and both are results worth keeping.
    """
    return QaRunResponse(**await service.run(payload.target_id))


@router.get(
    "/runs",
    response_model=list[QaRunResponse],
    summary="List QA runs, newest first",
)
async def list_qa_runs(
    service: QaServiceDep,
    limit: int = Query(
        DEFAULT_RUN_LIMIT,
        ge=1,
        le=200,
        description="Maximum number of runs to return.",
    ),
) -> list[QaRunResponse]:
    """Recent QA runs across all targets."""
    return [QaRunResponse(**run) for run in await service.list_runs(limit=limit)]


@router.get(
    "/runs/{run_id}",
    response_model=QaRunResponse,
    summary="Get one QA run",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_qa_run(run_id: str, service: QaServiceDep) -> QaRunResponse:
    """Full detail for a single QA run, including observations."""
    return QaRunResponse(**await service.get_run(run_id))
