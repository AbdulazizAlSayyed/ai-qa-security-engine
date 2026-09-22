"""Target registry endpoints.

These routes are deliberately thin. They validate input through the schemas,
call the service, and shape the response. Service failures are translated
into status codes by the exception handlers registered in ``app.main``, so
there is no error plumbing here.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.dependencies import TargetServiceDep
from app.schemas.target import (
    TargetCreate,
    TargetDeleteResponse,
    TargetResponse,
    TargetUpdate,
)

router = APIRouter(prefix="/targets", tags=["targets"])

_NOT_FOUND = {"description": "No target with that id."}
_BAD_ID = {"description": "The id is not a well-formed ObjectId."}
_DUPLICATE = {"description": "Another target already has this identity."}


@router.post(
    "",
    response_model=TargetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a target",
    responses={409: _DUPLICATE},
)
async def create_target(
    payload: TargetCreate, service: TargetServiceDep
) -> TargetResponse:
    """Add an application to the assessment inventory."""
    return TargetResponse(**await service.create(payload))


@router.get(
    "",
    response_model=list[TargetResponse],
    summary="List registered targets",
)
async def list_targets(service: TargetServiceDep) -> list[TargetResponse]:
    """Every registered target, newest first."""
    return [TargetResponse(**target) for target in await service.list_all()]


@router.get(
    "/{target_id}",
    response_model=TargetResponse,
    summary="Get one target",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_target(target_id: str, service: TargetServiceDep) -> TargetResponse:
    """Full detail for a single target."""
    return TargetResponse(**await service.get(target_id))


@router.patch(
    "/{target_id}",
    response_model=TargetResponse,
    summary="Update a target",
    responses={400: _BAD_ID, 404: _NOT_FOUND, 409: _DUPLICATE},
)
async def update_target(
    target_id: str, payload: TargetUpdate, service: TargetServiceDep
) -> TargetResponse:
    """Change some fields of a target. Omitted fields are left as they are."""
    return TargetResponse(**await service.update(target_id, payload))


@router.delete(
    "/{target_id}",
    response_model=TargetDeleteResponse,
    summary="Delete a target",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def delete_target(
    target_id: str, service: TargetServiceDep
) -> TargetDeleteResponse:
    """Remove a target from the registry."""
    await service.delete(target_id)
    return TargetDeleteResponse(deleted=True, id=target_id)
