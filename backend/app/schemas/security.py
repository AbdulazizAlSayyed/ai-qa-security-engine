"""Request and response schemas for the security engine API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.target import TargetType

SeverityLiteral = Literal["high", "medium", "low", "informational"]
ComponentStatusLiteral = Literal["completed", "skipped", "failed"]
RunStatusLiteral = Literal["completed", "failed", "error"]


class SecurityRunRequest(BaseModel):
    """Body for ``POST /security/runs``.

    Only a registered target id is accepted. The URLs are read from the
    registry, so a caller can never point this engine at something the
    platform was not authorised to scan.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    target_id: str = Field(
        min_length=1,
        description="Id of a registered, enabled target to assess.",
        examples=["000000000000000000000000"],
    )


class SecurityFinding(BaseModel):
    """A normalized finding, whatever scanner produced it."""

    id: str
    source: str
    rule_id: str | None = None
    name: str
    description: str | None = None
    severity: SeverityLiteral
    confidence: str | None = None
    url: str | None = None
    method: str | None = None
    parameter: str | None = None
    evidence: str | None = None
    solution: str | None = None
    reference: str | None = None
    cwe: str | None = None
    wasc: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SecurityComponent(BaseModel):
    """What one scanner did."""

    name: str
    status: ComponentStatusLiteral
    enabled: bool = True
    duration_ms: int = 0
    detail: str | None = Field(
        default=None,
        description="Why it was skipped, or how it failed.",
    )
    findings: list[SecurityFinding] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SecuritySummary(BaseModel):
    """Finding counts by severity."""

    total_findings: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0


class SecurityRunResponse(BaseModel):
    """A security assessment as the API exposes it."""

    id: str
    target_id: str
    target_name: str
    target_base_url: str
    target_api_url: str | None = None
    target_type: TargetType

    status: RunStatusLiteral
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    components: list[SecurityComponent] = Field(default_factory=list)
    findings: list[SecurityFinding] = Field(
        default_factory=list,
        description="Every component's findings, most severe first.",
    )
    summary: SecuritySummary = Field(default_factory=SecuritySummary)

    engine_metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(
        default=None,
        description="Why the engine itself could not execute, when that happened.",
    )
