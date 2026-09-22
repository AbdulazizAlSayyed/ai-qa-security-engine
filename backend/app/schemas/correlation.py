"""Request and response schemas for correlation & prioritization (Phase 6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.issue import IssueResponse

CorrelationStatusLiteral = Literal["running", "completed", "failed"]


class CorrelationRequest(BaseModel):
    """``POST /assessments/{id}/correlation`` takes no input.

    Everything is read from the stored assessment; any field is a 422.
    """

    model_config = ConfigDict(extra="forbid")


class CorrelationSummary(BaseModel):
    """The last correlation run, kept on the assessment as derived metadata."""

    status: CorrelationStatusLiteral
    started_at: datetime | None = None
    completed_at: datetime | None = None
    correlation_version: str | None = None
    priority_model_version: str | None = None
    ai_analysis_id: str | None = Field(
        default=None, description="Completed AI analysis used as supporting data, if any."
    )
    evidence_total: int = 0
    evidence_considered: int = 0
    evidence_excluded: dict[str, int] = Field(default_factory=dict)
    ai_references_ignored: int = 0
    group_count: int = 0
    issue_count: int = 0
    priority_counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class CorrelationGroupResponse(BaseModel):
    id: str
    correlation_group_id: str
    group_number: int
    assessment_id: str
    group_key: str
    correlation_rule: str
    correlation_rule_description: str
    correlation_reason: str
    correlation_version: str
    finding_type: Literal["qa", "security"]
    identity: str
    target_component: str
    affected_components: list[str]
    categories: list[str]
    sources: list[str]
    evidence_statuses: list[str]
    tool_severity: str | None = None
    representative_title: str
    representative_evidence_id: str
    evidence_ids: list[str]
    evidence_refs: list[str]
    evidence_count: int
    created_at: datetime
    updated_at: datetime


class CorrelationRunResponse(BaseModel):
    assessment_id: str
    correlation: CorrelationSummary
    issues: list[IssueResponse]
