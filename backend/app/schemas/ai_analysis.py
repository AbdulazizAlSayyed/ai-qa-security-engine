"""Request and response schemas for the AI analysis API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engines.ai.models import AIAnalysisResult

AnalysisStatusLiteral = Literal["created", "running", "completed", "failed"]


class AIAnalysisRequest(BaseModel):
    """``POST /assessments/{id}/ai-analysis`` takes no parameters.

    The model exists only to *refuse* input: the evidence analysed is always
    loaded by the backend from the assessment, so a body such as
    ``{"evidence": [...]}`` is a 422, never an alternative input path.
    """

    model_config = ConfigDict(extra="forbid")


class OmittedEvidence(BaseModel):
    ref: str
    evidence_id: str | None = None
    reason: str


class AnalysisContextInfo(BaseModel):
    total_evidence: int = 0
    supplied_evidence: int = 0
    omitted: list[OmittedEvidence] = Field(default_factory=list)
    truncated_fields: int = 0
    redactions: int = 0


class AnalysisError(BaseModel):
    category: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AIAnalysisResponse(BaseModel):
    """One analysis execution, as stored in ``ai_analysis_logs``."""

    id: str
    analysis_id: str
    assessment_id: str
    target_id: str | None = None
    provider: str
    model: str
    analysis_version: str
    status: AnalysisStatusLiteral
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    #: Every evidence record the model was shown (real evidence ids).
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    context: AnalysisContextInfo = Field(default_factory=AnalysisContextInfo)
    usage: dict[str, int] = Field(default_factory=dict)
    result: AIAnalysisResult | None = None
    error: AnalysisError | None = None


class AIAnalysisView(BaseModel):
    """What ``GET /assessments/{id}/ai-analysis`` returns."""

    assessment_id: str
    status: Literal["not_analyzed", "created", "running", "completed", "failed"]
    #: The most recent attempt, whatever its outcome.
    latest: AIAnalysisResponse | None = None
    #: The most recent attempt that completed and passed validation.
    latest_completed: AIAnalysisResponse | None = None
