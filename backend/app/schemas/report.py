"""Request and response schemas for reports (Phase 10)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReportStatusLiteral = Literal["running", "completed", "failed"]


class ReportRequest(BaseModel):
    """``POST .../reports`` takes no input: every source record is loaded by the server."""

    model_config = ConfigDict(extra="forbid")


class ReportArtifact(BaseModel):
    format: Literal["html", "pdf"]
    media_type: str
    size_bytes: int
    sha256: str
    filename: str


class ReportSourceSnapshot(BaseModel):
    assessment_id: str
    assessment_status: str
    partial: bool
    qa_run_id: str | None = None
    security_run_id: str | None = None
    evidence_count: int
    ai_analysis_id: str | None = None
    ai_analysis_status: str
    correlation_status: str
    correlation_version: str | None = None
    priority_model_version: str | None = None
    group_count: int
    issue_count: int
    recommendation_status: str
    recommendation_set: str | None = None
    recommendation_count: int
    retest_count: int


class TraceabilityErrorItem(BaseModel):
    relationship: str
    source: str
    reference: str
    problem: str


class ReportTraceability(BaseModel):
    status: Literal["passed", "failed"]
    checked_at: datetime
    links_checked: int
    checks: dict[str, int] = Field(default_factory=dict)
    errors: list[TraceabilityErrorItem] = Field(default_factory=list)


class RetestCounts(BaseModel):
    """Outcomes of the stored retests. Execution failures have no verdict."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    execution_failed: int = 0
    running: int = 0


class ReportSummary(BaseModel):
    assessment_status: str
    partial: bool
    qa: dict[str, int] = Field(default_factory=dict)
    security: dict[str, int] = Field(default_factory=dict)
    evidence_total: int
    issue_total: int
    priority_counts: dict[str, int] = Field(default_factory=dict)
    ai_analysis_status: str
    correlation_status: str
    recommendation_status: str
    recommendation_count: int
    retests: RetestCounts


class ReportError(BaseModel):
    category: str
    message: str


class ReportResponse(BaseModel):
    id: str
    report_id: str
    report_number: int
    assessment_id: str
    target_id: str
    target_name: str | None = None
    report_version: str
    status: ReportStatusLiteral
    source_fingerprint: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    formats: list[Literal["html", "pdf"]] = Field(default_factory=list)
    source_snapshot: ReportSourceSnapshot | None = None
    traceability: ReportTraceability | None = None
    summary: ReportSummary | None = None
    artifacts: dict[str, ReportArtifact] = Field(default_factory=dict)
    error: ReportError | None = None
    updated_at: datetime
    #: Set on the POST response only: true when unchanged source data
    #: matched an existing report, which is returned instead of a duplicate.
    reused: bool = False
