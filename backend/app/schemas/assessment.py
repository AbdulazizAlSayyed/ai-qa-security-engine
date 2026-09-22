"""Request and response schemas for the assessment orchestrator API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.target import TargetType
from app.schemas.correlation import CorrelationSummary
from app.schemas.recommendation import RecommendationSummary

AssessmentStateLiteral = Literal[
    "created",
    "running",
    "qa_running",
    "security_running",
    "normalizing",
    "analyzing",
    "completed",
    "failed",
]
StageStatusLiteral = Literal["pending", "running", "completed", "failed"]
EvidenceTypeLiteral = Literal["qa", "security"]
EvidenceStatusLiteral = Literal["passed", "failed", "skipped", "error", "observed"]


class AssessmentRequest(BaseModel):
    """Body for ``POST /assessments``.

    A registered target id only. Like the QA and security endpoints, no URL
    may be supplied by the caller - ``extra="forbid"`` turns one into a 422.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    target_id: str = Field(
        min_length=1,
        description="Id of a registered, enabled web target to assess.",
        examples=["000000000000000000000000"],
    )


class StateTransition(BaseModel):
    state: AssessmentStateLiteral
    timestamp: datetime
    message: str | None = None


class Evidence(BaseModel):
    """One normalized piece of evidence, from either engine."""

    id: str
    evidence_id: str
    assessment_id: str
    sequence: int = 0
    source: str = Field(description="playwright, zap, api_probe or semgrep.")
    finding_type: EvidenceTypeLiteral
    category: str
    title: str
    target_component: str
    status: EvidenceStatusLiteral
    expected: str | None = Field(
        default=None,
        description="Only set when the check genuinely asserted something. "
        "Null for scanner findings.",
    )
    actual: str | None = None
    tool_severity: str | None = Field(
        default=None, description="The scanner's own severity, never assigned here."
    )
    source_run_id: str | None = None
    source_finding_id: str | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class QaSummary(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: int = 0


class SecuritySummary(BaseModel):
    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0


class AssessmentSummary(BaseModel):
    qa: QaSummary = Field(default_factory=QaSummary)
    security: SecuritySummary = Field(default_factory=SecuritySummary)
    total_findings: int = Field(
        default=0, description="Failed QA checks plus security findings of every severity."
    )
    evidence_total: int = 0


class CoverageItem(BaseModel):
    source: str
    status: str
    detail: str | None = None


class AssessmentResponse(BaseModel):
    """An assessment as the API exposes it. Evidence is fetched separately."""

    id: str
    target_id: str
    target_name: str
    target_base_url: str
    target_api_url: str | None = None
    target_type: TargetType

    status: AssessmentStateLiteral
    state_history: list[StateTransition] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None

    #: Ids of the raw runs. The runs stay in their own collections.
    qa_run_id: str | None = None
    qa_status: StageStatusLiteral = "pending"
    qa_run_status: str | None = Field(
        default=None, description="The QA run's own verdict: passed, failed or error."
    )
    qa_error: str | None = None

    security_run_id: str | None = None
    security_status: StageStatusLiteral = "pending"
    security_run_status: str | None = Field(
        default=None,
        description="The security run's own verdict: completed, failed or error.",
    )
    security_error: str | None = None

    partial: bool = Field(
        default=False, description="True when one engine stage could not execute."
    )
    security_coverage: list[CoverageItem] = Field(default_factory=list)
    evidence_count: int = 0
    summary: AssessmentSummary = Field(default_factory=AssessmentSummary)

    #: Phase 5, attached after the fact. Never changes the technical result.
    ai_analysis_status: Literal["not_analyzed", "running", "completed", "failed"] = "not_analyzed"
    ai_analysis_id: str | None = None

    #: Phase 6, derived metadata of the last correlation & prioritization run.
    #: Never changes the technical result or the lifecycle state.
    correlation: CorrelationSummary | None = None

    #: Phase 8, derived metadata of the last advisory recommendation generation.
    recommendation: RecommendationSummary | None = None

    error: str | None = Field(
        default=None,
        description="Why the assessment failed, when it did.",
    )
