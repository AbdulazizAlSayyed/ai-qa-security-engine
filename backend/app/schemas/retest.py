"""Request and response schemas for retests (Phase 9)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engines.remediation.models import PassCondition, RetestCheck, RetestScope, RetestType

#: Did the retest execute?
RetestStatusLiteral = Literal["running", "completed", "failed"]
#: What did it conclude? Only set when status == "completed".
VerdictLiteral = Literal["PASS", "FAIL"]


class RetestRequest(BaseModel):
    """``POST .../retest`` takes no input: the stored specification is executed."""

    model_config = ConfigDict(extra="forbid")


class RetestPlanInfo(BaseModel):
    engine: Literal["qa", "security"]
    components: list[str] = Field(default_factory=list)
    qa_checks: list[str] = Field(default_factory=list)


class SourceRun(BaseModel):
    """The raw run the retest produced, in qa_runs / security_runs."""

    engine: Literal["qa", "security"]
    run_id: str
    status: str | None = None


class RetestObservation(BaseModel):
    """One new normalized result that decided the verdict (not stored as evidence)."""

    source: str | None = None
    finding_type: str | None = None
    title: str | None = None
    target_component: str | None = None
    status: str | None = None
    tool_severity: str | None = None
    correlation_key: str
    source_run_id: str | None = None
    source_finding_id: str | None = None


class ResultSummary(BaseModel):
    engine: Literal["qa", "security"]
    results_evaluated: int
    matching_results: int
    reason: str


class RetestError(BaseModel):
    category: str
    message: str


class RetestResponse(BaseModel):
    id: str
    retest_id: str
    retest_number: int
    assessment_id: str
    target_id: str
    recommendation_id: str
    recommendation_ref: str
    ai_analysis_id: str
    issue_id: str
    correlation_group_id: str | None = None
    type: RetestType
    scope: RetestScope
    target_component: str
    match_key: str
    pass_condition: PassCondition
    checks: list[RetestCheck]
    plan: RetestPlanInfo
    status: RetestStatusLiteral
    verdict: VerdictLiteral | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    source_run_ids: list[str] = Field(default_factory=list)
    source_runs: list[SourceRun] = Field(default_factory=list)
    #: On FAIL: the original evidence (checks of the specification) whose
    #: condition was observed again. Empty on PASS. References only - the
    #: original assessment's evidence is never changed.
    matched_evidence_ids: list[str] = Field(default_factory=list)
    matched_evidence_refs: list[str] = Field(default_factory=list)
    observations: list[RetestObservation] = Field(default_factory=list)
    result_summary: ResultSummary | None = None
    error: RetestError | None = None
    retest_version: str
    created_at: datetime
    updated_at: datetime
