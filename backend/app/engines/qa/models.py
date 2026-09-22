"""Engine-level result types for the QA engine.

These are plain dataclasses on purpose. The engine is the layer that knows
about browsers, not about HTTP or MongoDB, so it returns structured Python
objects and lets the service decide how to persist and expose them.

Status vocabulary (shared by tests and runs):

``passed``
    The check succeeded.
``failed``
    The check ran and the application did not meet the assertion. This is a
    finding about the *target*, not about the platform.
``error``
    The check could not be executed at all - the browser would not launch,
    an unexpected exception escaped, and so on. This is a finding about the
    *engine*, and must never be confused with a genuine test failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TestStatus(str, Enum):
    # Tells pytest this is domain vocabulary, not a test class to collect.
    # Dunder names are never turned into enum members, so this is safe.
    __test__ = False

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class RunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class TestResult:
    """Outcome of a single smoke test."""

    # Not a pytest test class. Unannotated, so it stays out of the fields.
    __test__ = False

    name: str
    status: TestStatus
    duration_ms: int
    url: str | None = None
    title: str | None = None
    error: str | None = None
    #: Anything else the test observed. Keeps the shape extensible without
    #: growing a sparse column per test type.
    details: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "url": self.url,
            "title": self.title,
            "error": self.error,
            "details": self.details,
        }


@dataclass
class ConsoleError:
    """A browser console error or uncaught page exception."""

    type: str
    message: str
    location: str | None = None

    def to_document(self) -> dict[str, Any]:
        return {"type": self.type, "message": self.message, "location": self.location}


@dataclass
class NetworkFailure:
    """A request that failed outright, or a response with a 4xx/5xx status."""

    url: str
    method: str
    status: int | None = None
    failure: str | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "method": self.method,
            "status": self.status,
            "failure": self.failure,
        }


@dataclass
class QaRunOutcome:
    """Everything one execution of the smoke suite produced."""

    status: RunStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    tests: list[TestResult] = field(default_factory=list)
    console_errors: list[ConsoleError] = field(default_factory=list)
    network_failures: list[NetworkFailure] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Set only when the engine itself could not execute.
    error: str | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "tests": [test.to_document() for test in self.tests],
            "console_errors": [item.to_document() for item in self.console_errors],
            "network_failures": [item.to_document() for item in self.network_failures],
            "metadata": self.metadata,
            "error": self.error,
        }


def derive_run_status(tests: list[TestResult]) -> RunStatus:
    """Roll individual test outcomes up into a run status.

    A genuine assertion failure outranks an engine error in the report,
    because "the application is broken" is the more actionable headline; an
    engine error with no failures still surfaces as ``error``.
    """
    if any(test.status is TestStatus.FAILED for test in tests):
        return RunStatus.FAILED
    if any(test.status is TestStatus.ERROR for test in tests):
        return RunStatus.ERROR
    return RunStatus.PASSED
