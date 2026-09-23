"""Requirements registry endpoints, nested under the target they describe.

The nesting is the point, exactly as it is for test accounts: every path
names a target, the service queries on both the target and the requirement,
and there is no route that reaches a requirement without saying which target
it belongs to.

Two of these routes read a document and propose requirements. Neither one
writes anything: they answer with candidates, and the *only* route that
creates requirements from them is ``/import``, which takes a body a human
sent after reviewing those candidates. That separation is the human approval
step - there is no code path from a model's answer to the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.dependencies import RequirementServiceDep
from app.schemas.requirement import (
    OpenApiImportRequest,
    RequirementArea,
    RequirementCreate,
    RequirementDeleteResponse,
    RequirementExtractionRequest,
    RequirementExtractionResponse,
    RequirementImportRequest,
    RequirementImportResponse,
    RequirementPriority,
    RequirementResponse,
    RequirementSource,
    RequirementStatus,
    RequirementUpdate,
)

router = APIRouter(prefix="/targets/{target_id}/requirements", tags=["requirements"])

_NOT_FOUND = {"description": "No such target, or no such requirement on that target."}
_BAD_ID = {"description": "The target or requirement id is not a well-formed ObjectId."}
_UNREADABLE = {"description": "The supplied document could not be read."}
_PROVIDER_DOWN = {"description": "No AI provider is configured."}
_PROVIDER_FAILED = {"description": "The provider failed, or its answer was rejected."}


@router.post(
    "",
    response_model=RequirementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Write a requirement for a target",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def create_requirement(
    target_id: str, payload: RequirementCreate, service: RequirementServiceDep
) -> RequirementResponse:
    """Record what this target is supposed to do.

    The ``REQ-NNN`` key is allocated by the registry; the body has no field
    for one.
    """
    return RequirementResponse(**await service.create(target_id, payload))


@router.get(
    "",
    response_model=list[RequirementResponse],
    summary="List a target's requirements",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def list_requirements(
    target_id: str,
    service: RequirementServiceDep,
    requirement_status: RequirementStatus | None = Query(
        default=None, alias="status", description="Only requirements in this state."
    ),
    priority: RequirementPriority | None = Query(default=None),
    area: RequirementArea | None = Query(default=None),
    source: RequirementSource | None = Query(default=None),
) -> list[RequirementResponse]:
    """The registry in REQ order, narrowed by any combination of the filters."""
    requirements = await service.list_for_target(
        target_id,
        status=requirement_status.value if requirement_status else None,
        priority=priority.value if priority else None,
        area=area.value if area else None,
        source=source.value if source else None,
    )
    return [RequirementResponse(**requirement) for requirement in requirements]


@router.post(
    "/extract-from-brd",
    response_model=RequirementExtractionResponse,
    summary="Propose requirements from a business document (nothing is stored)",
    responses={
        400: _BAD_ID,
        404: _NOT_FOUND,
        502: _PROVIDER_FAILED,
        503: _PROVIDER_DOWN,
    },
)
async def extract_from_brd(
    target_id: str,
    payload: RequirementExtractionRequest,
    service: RequirementServiceDep,
) -> RequirementExtractionResponse:
    """Read a BRD and answer with candidates for a human to review.

    Nothing is written to the registry by this call, and the document is not
    stored. Accepting a candidate is a separate, deliberate request to
    ``/import``.
    """
    return RequirementExtractionResponse(
        **await service.extract_from_brd(target_id, payload.document)
    )


@router.post(
    "/extract-from-openapi",
    response_model=RequirementExtractionResponse,
    summary="Propose requirements from an OpenAPI document, offline (nothing is stored)",
    responses={400: _BAD_ID, 404: _NOT_FOUND, 422: _UNREADABLE},
)
async def extract_from_openapi(
    target_id: str,
    payload: OpenApiImportRequest,
    service: RequirementServiceDep,
) -> RequirementExtractionResponse:
    """Parse an OpenAPI document into candidates.

    The document is read where it stands. The API it describes is never
    contacted, no operation is executed, and no ``$ref`` is dereferenced.
    """
    return RequirementExtractionResponse(
        **await service.extract_from_openapi(target_id, payload.document)
    )


@router.post(
    "/import",
    response_model=RequirementImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Write the candidates a human accepted",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def import_requirements(
    target_id: str,
    payload: RequirementImportRequest,
    service: RequirementServiceDep,
) -> RequirementImportResponse:
    """The approval step: create requirements from a reviewed list.

    Every entry is validated exactly as a hand-written requirement is, and
    gets its key the same way. Whatever the reviewer edited is what is
    stored; whatever they rejected never reaches this route.
    """
    created = await service.import_approved(
        target_id, payload.requirements, extraction_id=payload.extraction_id
    )
    return RequirementImportResponse(
        created=[RequirementResponse(**item) for item in created], count=len(created)
    )


@router.get(
    "/{requirement_id}",
    response_model=RequirementResponse,
    summary="Get one requirement",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_requirement(
    target_id: str, requirement_id: str, service: RequirementServiceDep
) -> RequirementResponse:
    """One statement, addressed through the target it was written for."""
    return RequirementResponse(**await service.get(target_id, requirement_id))


@router.patch(
    "/{requirement_id}",
    response_model=RequirementResponse,
    summary="Update a requirement",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def update_requirement(
    target_id: str,
    requirement_id: str,
    payload: RequirementUpdate,
    service: RequirementServiceDep,
) -> RequirementResponse:
    """Change some fields. The key never changes, and neither does the target.

    ``acceptance_criteria`` is replaced whole: send back the ids you want to
    keep, omit an id to add a new criterion, and leave one out entirely to
    remove it.
    """
    return RequirementResponse(
        **await service.update(target_id, requirement_id, payload)
    )


@router.delete(
    "/{requirement_id}",
    response_model=RequirementDeleteResponse,
    summary="Delete a requirement",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def delete_requirement(
    target_id: str, requirement_id: str, service: RequirementServiceDep
) -> RequirementDeleteResponse:
    """Remove the statement.

    A gap in the middle of the series is never filled, but deleting the
    highest-numbered requirement frees that number for the next create. To
    keep both the record and the key, set ``status`` to ``deprecated``
    instead.
    """
    removed = await service.delete(target_id, requirement_id)
    return RequirementDeleteResponse(
        deleted=True, id=requirement_id, key=str(removed.get("key", ""))
    )
