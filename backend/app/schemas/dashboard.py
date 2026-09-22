"""Response schema for the dashboard aggregation (Phase 7).

Every number is computed on request from the existing collections
(``assessments``, ``issues``, ``targets``). Nothing here is stored, and
nothing is a new concept: statuses, QA outcomes, tool severities and
priorities use the vocabularies Phases 2-6 already defined.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.assessment import AssessmentStateLiteral, StageStatusLiteral


class QaCounts(BaseModel):
    """Sums of ``assessments.summary.qa`` (checks per outcome)."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: int = 0


class SecurityCounts(BaseModel):
    """Sums of ``assessments.summary.security``, by the scanner's own severity."""

    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0


class PriorityCounts(BaseModel):
    """Counts of stored ``issues`` documents by their Phase 6 priority."""

    total: int = 0
    P1: int = 0
    P2: int = 0
    P3: int = 0
    P4: int = 0


class AssessmentCounts(BaseModel):
    total: int = 0
    #: Count per stored lifecycle status (only statuses that occur).
    by_status: dict[str, int] = Field(default_factory=dict)
    completed: int = 0
    failed: int = 0
    #: Pipeline still working: created, running, qa_running, security_running, normalizing.
    running: int = 0
    #: Completed assessments whose AI analysis is in progress right now.
    analyzing: int = 0
    #: One engine stage could not execute (Phase 4 ``partial``).
    partial: int = 0
    ai_analyzed: int = 0
    correlated: int = 0


class IssueSummary(BaseModel):
    by_priority: PriorityCounts = Field(default_factory=PriorityCounts)
    by_type: dict[str, int] = Field(default_factory=dict)
    #: How many assessments the issues above come from.
    assessments_with_issues: int = 0


class TargetCounts(BaseModel):
    total: int = 0
    enabled: int = 0


class HistoryItem(BaseModel):
    id: str
    target_id: str
    target_name: str
    status: AssessmentStateLiteral
    partial: bool = False
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    qa_status: StageStatusLiteral = "pending"
    security_status: StageStatusLiteral = "pending"
    qa: QaCounts = Field(default_factory=QaCounts)
    security: SecurityCounts = Field(default_factory=SecurityCounts)
    total_findings: int = 0
    evidence_count: int = 0
    ai_analysis_status: Literal["not_analyzed", "running", "completed", "failed"] = "not_analyzed"
    #: ``not_correlated`` until Phase 6 has run on the assessment.
    correlation_status: Literal["not_correlated", "running", "completed", "failed"] = (
        "not_correlated"
    )
    #: Counted from the assessment's actual ``issues`` documents.
    issues: PriorityCounts = Field(default_factory=PriorityCounts)


class TrendPoint(BaseModel):
    """One UTC day that has at least one assessment (by ``created_at``)."""

    date: str = Field(description="UTC calendar day, YYYY-MM-DD.")
    assessments: int = 0
    completed: int = 0
    failed: int = 0
    partial: int = 0
    qa_failed: int = 0
    security: SecurityCounts = Field(default_factory=SecurityCounts)
    issues: PriorityCounts = Field(default_factory=PriorityCounts)


class DashboardResponse(BaseModel):
    generated_at: datetime
    trend_days: int
    history_limit: int
    targets: TargetCounts
    assessments: AssessmentCounts
    #: Totals over every stored assessment.
    qa: QaCounts
    security: SecurityCounts
    #: Totals over every stored issue (only correlated assessments have issues).
    issues: IssueSummary
    #: The newest assessment whose technical result is final (completed).
    latest: HistoryItem | None = None
    #: Newest first, by ``created_at``.
    history: list[HistoryItem]
    #: Oldest day first; days without an assessment are not returned.
    trends: list[TrendPoint]
