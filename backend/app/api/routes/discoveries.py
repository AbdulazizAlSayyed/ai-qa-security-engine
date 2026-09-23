"""Application discovery endpoints, nested under the target they explore.

Same nesting as test accounts and requirements: every path names a target,
the service queries on both the target and the run, and there is no route
that reaches a map without saying which application it belongs to.

Starting a discovery is a real browser run and is therefore slow by nature -
the request returns when the crawl has finished and the map has been stored,
which is the honest thing to do: a 201 that arrived before the browser
opened would say nothing about whether the target was reachable.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.dependencies import DiscoveryServiceDep
from app.schemas.discovery import (
    ApplicationMapResponse,
    DiscoveryRunView,
    DiscoveryStartRequest,
)

router = APIRouter(prefix="/targets/{target_id}", tags=["discovery"])

_NOT_FOUND = {"description": "No such target, or no such discovery on that target."}
_BAD_ID = {"description": "The target id is not a well-formed ObjectId."}
_NOT_DISCOVERABLE = {"description": "The target exists but cannot be explored."}


@router.post(
    "/discoveries",
    response_model=ApplicationMapResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Explore a target and store the application map it produced",
    responses={400: _BAD_ID, 404: _NOT_FOUND, 409: _NOT_DISCOVERABLE},
)
async def start_discovery(
    target_id: str,
    payload: DiscoveryStartRequest,
    service: DiscoveryServiceDep,
) -> ApplicationMapResponse:
    """Run a bounded crawl with a real browser and return the map.

    A run that could not reach the application is stored and returned with
    status ``failed`` and the reason, because "the platform cannot see your
    application" is a result worth keeping, not an error to discard.
    """
    return ApplicationMapResponse(**await service.run(target_id, payload))


@router.get(
    "/discoveries",
    response_model=list[DiscoveryRunView],
    summary="List a target's discovery runs",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def list_discoveries(
    target_id: str,
    service: DiscoveryServiceDep,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[DiscoveryRunView]:
    """Recent runs, newest first, with their counts but without their maps."""
    return [
        DiscoveryRunView(**run) for run in await service.list_for_target(target_id, limit)
    ]


@router.get(
    "/application-map",
    response_model=ApplicationMapResponse,
    summary="The target's most recent application map",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def latest_application_map(
    target_id: str, service: DiscoveryServiceDep
) -> ApplicationMapResponse:
    """The newest map, whatever its outcome.

    Deliberately not "the newest successful one": returning an older map
    while the latest run failed would quietly present stale structure as
    current.
    """
    return ApplicationMapResponse(**await service.latest_map(target_id))


@router.get(
    "/discoveries/{discovery_id}",
    response_model=ApplicationMapResponse,
    summary="One discovery run and its map",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_discovery(
    target_id: str, discovery_id: str, service: DiscoveryServiceDep
) -> ApplicationMapResponse:
    """Addressed by the run's own id, or by its ObjectId. Both within the target."""
    return ApplicationMapResponse(**await service.get(target_id, discovery_id))
