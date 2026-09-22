"""Response schemas for prioritized issues (Phase 6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PriorityLiteral = Literal["P1", "P2", "P3", "P4"]
IssueTypeLiteral = Literal["qa", "security"]
ToolSeverityLiteral = Literal["high", "medium", "low", "informational"]


class ScoreFactor(BaseModel):
    """One named term of the priority score."""

    factor: Literal["base", "spread", "repetition", "corroboration", "ai_support"]
    points: int
    detail: str


class IssueAIFinding(BaseModel):
    """A finding from a completed AI analysis that cites this issue's evidence."""

    finding_id: str
    title: str
    status: str
    confidence: str
    evidence_refs: list[str] = Field(default_factory=list)


class IssueResponse(BaseModel):
    id: str
    issue_id: str = Field(description="Human-readable reference, unique per assessment.")
    issue_number: int
    assessment_id: str
    correlation_group_id: str
    group_key: str
    type: IssueTypeLiteral
    title: str
    description: str
    priority: PriorityLiteral = Field(description="Derived ranking. Not a severity.")
    priority_score: int
    priority_reasons: list[str]
    score_factors: list[ScoreFactor]
    priority_model_version: str
    tool_severity: ToolSeverityLiteral | None = Field(
        default=None, description="Most severe tool severity among the evidence, as reported."
    )
    confidence: Literal["high", "medium", "low"] | None = Field(
        default=None,
        description="Confidence of the supporting AI finding that was counted, if any.",
    )
    affected_components: list[str]
    sources: list[str]
    correlation_rule: str
    evidence_ids: list[str]
    evidence_refs: list[str]
    evidence_count: int
    ai_analysis_id: str | None = None
    ai_finding_ids: list[str] = Field(default_factory=list)
    ai_findings: list[IssueAIFinding] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
