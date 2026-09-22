"""Request and response schemas for advisory recommendations (Phase 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engines.remediation.models import Recommendation

GenerationStatusLiteral = Literal["running", "completed", "failed"]


class RecommendationRequest(BaseModel):
    """``POST .../recommendations`` takes no input; any field is a 422."""

    model_config = ConfigDict(extra="forbid")


class GenerationError(BaseModel):
    category: str
    message: str


class RecommendationSummary(BaseModel):
    """The last generation attempt, kept on the assessment as derived metadata."""

    status: GenerationStatusLiteral
    generation_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    ai_analysis_id: str | None = None
    correlation_completed_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    recommendation_version: str | None = None
    issues_supplied: int = 0
    issues_omitted: list[str] = Field(default_factory=list)
    evidence_supplied: int = 0
    evidence_omitted: int = 0
    redactions: int = 0
    recommendation_count: int = 0
    usage: dict[str, int] = Field(default_factory=dict)
    error: GenerationError | None = None


class RecommendationResponse(Recommendation):
    id: str
    created_at: datetime
    updated_at: datetime


class RecommendationSet(BaseModel):
    """One stored set: the recommendations generated from one AI analysis."""

    ai_analysis_id: str
    count: int
    updated_at: datetime


class RecommendationsView(BaseModel):
    assessment_id: str
    status: Literal["not_generated", "running", "completed", "failed"]
    #: The last generation attempt (may have failed), or null.
    generation: RecommendationSummary | None = None
    #: The latest completed AI analysis of the assessment right now.
    current_ai_analysis_id: str | None = None
    #: Which set ``recommendations`` belongs to.
    ai_analysis_id: str | None = None
    #: The shown set was generated from the current AI analysis and the
    #: current correlation. False means regenerate to catch up.
    is_current: bool = False
    sets: list[RecommendationSet] = Field(default_factory=list)
    recommendations: list[RecommendationResponse] = Field(default_factory=list)
