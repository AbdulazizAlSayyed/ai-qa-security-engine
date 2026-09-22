"""Prioritized issue endpoints (Phase 6). Read-only."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.api.dependencies import IssueServiceDep
from app.schemas.issue import IssueResponse
from app.services.issue_service import DEFAULT_ISSUE_LIMIT, MAX_ISSUE_LIMIT

router = APIRouter(prefix="/assessments", tags=["issues"])

_BAD_ID = {"description": "The assessment id is malformed."}


@router.get(
    "/{assessment_id}/issues",
    response_model=list[IssueResponse],
    summary="Prioritized issues: P1 first, then score, then issue number",
    responses={400: _BAD_ID, 404: {"description": "No such assessment."}},
)
async def list_issues(
    assessment_id: str,
    service: IssueServiceDep,
    type: Literal["qa", "security"] | None = Query(default=None),
    priority: Literal["P1", "P2", "P3", "P4"] | None = Query(default=None),
    limit: int = Query(DEFAULT_ISSUE_LIMIT, ge=1, le=MAX_ISSUE_LIMIT),
) -> list[IssueResponse]:
    """Empty until the assessment has been correlated."""
    items = await service.list_issues(
        assessment_id, issue_type=type, priority=priority, limit=limit
    )
    return [IssueResponse(**item) for item in items]


@router.get(
    "/{assessment_id}/issues/{issue_id}",
    response_model=IssueResponse,
    summary="One issue with its priority reasons, evidence and AI finding references",
    responses={
        400: {"description": "Malformed assessment id or issue reference."},
        404: {"description": "No such assessment, or no such issue in it."},
    },
)
async def get_issue(assessment_id: str, issue_id: str, service: IssueServiceDep) -> IssueResponse:
    return IssueResponse(**await service.get_issue(assessment_id, issue_id))
