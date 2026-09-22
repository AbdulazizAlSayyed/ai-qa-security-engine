"""Request and response schemas for the QA engine API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.target import TargetType

TestStatusLiteral = Literal["passed", "failed", "error"]
RunStatusLiteral = Literal["passed", "failed", "error"]


class QaRunRequest(BaseModel):
    """Body for ``POST /qa/runs``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    target_id: str = Field(
        min_length=1,
        description="Id of a registered, enabled target to assess.",
        # A neutral placeholder: no real target's id belongs in the codebase.
        examples=["000000000000000000000000"],
    )


class QaTestResult(BaseModel):
    """One smoke test's outcome."""

    name: str
    status: TestStatusLiteral
    duration_ms: int
    url: str | None = None
    title: str | None = None
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class QaConsoleError(BaseModel):
    """A browser console error or uncaught page exception."""

    type: str
    message: str
    location: str | None = None


class QaNetworkFailure(BaseModel):
    """A failed request, or a response with a 4xx/5xx status."""

    url: str
    method: str
    status: int | None = None
    failure: str | None = None


class QaRunResponse(BaseModel):
    """A QA execution as the API exposes it."""

    id: str
    target_id: str
    target_name: str
    target_base_url: str
    target_type: TargetType

    status: RunStatusLiteral
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    tests: list[QaTestResult] = Field(default_factory=list)
    console_errors: list[QaConsoleError] = Field(default_factory=list)
    network_failures: list[QaNetworkFailure] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(
        default=None,
        description="Why the engine itself could not execute, when that happened.",
    )
