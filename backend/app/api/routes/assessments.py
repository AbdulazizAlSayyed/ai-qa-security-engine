"""Assessment orchestration endpoints.

One request runs the whole pipeline: QA, then security, then normalization.
As with the QA and security routes, the caller identifies a registered
target and never supplies a URL.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.dependencies import AssessmentServiceDep
from app.schemas.assessment import (
    AssessmentRequest,
    AssessmentResponse,
    Evidence,
)
from app.services.assessment_service import (
    DEFAULT_ASSESSMENT_LIMIT,
    DEFAULT_EVIDENCE_LIMIT,
    MAX_EVIDENCE_LIMIT,
)

router = APIRouter(prefix="/assessments", tags=["assessments"])

_BAD_ID = {"description": "The id is not a well-formed ObjectId."}
_NOT_FOUND = {"description": "No such assessment."}


@router.post(
    "",
    response_model=AssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run the full QA + security pipeline against a registered target",
    responses={
        400: {"description": "The target id is not a well-formed ObjectId."},
        404: {"description": "No such target."},
        409: {"description": "The target is disabled or not a web target."},
        500: {"description": "The orchestrator or its persistence failed."},
    },
)
async def create_assessment(
    payload: AssessmentRequest, service: AssessmentServiceDep
) -> AssessmentResponse:
    """Run both engines and store the unified, normalized result.

    Returns 201 whenever the pipeline ran and was recorded - however many
    tests failed or vulnerabilities were found, and also when an engine
    could not execute (the assessment then says so in ``status``,
    ``partial`` and the per-stage fields).
    """
    return AssessmentResponse(**await service.run(payload.target_id))


@router.get(
    "",
    response_model=list[AssessmentResponse],
    summary="List assessments, newest first",
)
async def list_assessments(
    service: AssessmentServiceDep,
    limit: int = Query(
        DEFAULT_ASSESSMENT_LIMIT,
        ge=1,
        le=100,
        description="Maximum number of assessments to return.",
    ),
) -> list[AssessmentResponse]:
    """Recent assessments across all targets, including any still running."""
    return [
        AssessmentResponse(**assessment)
        for assessment in await service.list_assessments(limit=limit)
    ]


@router.get(
    "/{assessment_id}",
    response_model=AssessmentResponse,
    summary="Get one assessment",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_assessment(
    assessment_id: str, service: AssessmentServiceDep
) -> AssessmentResponse:
    """Target snapshot, state, history, run ids, stage outcomes and summary."""
    return AssessmentResponse(**await service.get_assessment(assessment_id))


@router.get(
    "/{assessment_id}/evidence",
    response_model=list[Evidence],
    summary="Get the normalized evidence for an assessment",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_assessment_evidence(
    assessment_id: str,
    service: AssessmentServiceDep,
    limit: int = Query(
        DEFAULT_EVIDENCE_LIMIT,
        ge=1,
        le=MAX_EVIDENCE_LIMIT,
        description="Maximum number of evidence records to return.",
    ),
) -> list[Evidence]:
    """The evidence set on its own - what the AI layer will consume."""
    return [
        Evidence(**item) for item in await service.get_evidence(assessment_id, limit=limit)
    ]
