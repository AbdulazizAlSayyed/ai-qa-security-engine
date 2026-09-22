"""Engine-level result types for the security engine.

Mirrors the shape the QA engine established in Phase 2: plain dataclasses,
no HTTP and no MongoDB, returned to a service that decides how to persist
and expose them.

Two vocabularies matter here and must not be confused.

**Severity** describes a *finding* about the target:
``high`` / ``medium`` / ``low`` / ``informational``.

**Component status** describes whether a *scanner* did its job:

``completed``
    The scanner ran to the end.
``skipped``
    The scanner was legitimately not applicable - disabled in config, no
    API URL on the target, no source path for Semgrep, no authorised
    credentials for authenticated probes. Not a problem.
``failed``
    The scanner was asked to run and could not finish. A scanner problem,
    not a finding, and not an engine crash.

A vulnerable target produces findings and a ``completed`` run. Only the
platform breaking produces ``error``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


#: Most severe first. Used for sorting and for summary ordering.
SEVERITY_ORDER: list[Severity] = [
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFORMATIONAL,
]


class ComponentStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class SecurityFinding:
    """One normalized security finding, whatever scanner produced it."""

    source: str
    name: str
    severity: Severity
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    rule_id: str | None = None
    description: str | None = None
    confidence: str | None = None
    url: str | None = None
    method: str | None = None
    parameter: str | None = None
    evidence: str | None = None
    solution: str | None = None
    reference: str | None = None
    cwe: str | None = None
    wasc: str | None = None
    #: Scanner-specific extras preserved verbatim, so nothing is lost.
    raw: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "url": self.url,
            "method": self.method,
            "parameter": self.parameter,
            "evidence": self.evidence,
            "solution": self.solution,
            "reference": self.reference,
            "cwe": self.cwe,
            "wasc": self.wasc,
            "raw": self.raw,
        }


@dataclass
class ComponentResult:
    """What one scanner did, plus whatever it found."""

    name: str
    status: ComponentStatus
    enabled: bool = True
    duration_ms: int = 0
    #: Why it was skipped or how it failed. Always set when not completed.
    detail: str | None = None
    findings: list[SecurityFinding] = field(default_factory=list)
    #: Non-finding observations (reachability timings, headers seen, ...).
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "enabled": self.enabled,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
            "findings": [finding.to_document() for finding in self.findings],
            "metadata": self.metadata,
        }


@dataclass
class SecurityRunOutcome:
    """Everything one security execution produced."""

    status: RunStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    components: list[ComponentResult] = field(default_factory=list)
    engine_metadata: dict[str, Any] = field(default_factory=dict)
    #: Set only when the engine itself could not execute.
    error: str | None = None

    @property
    def findings(self) -> list[SecurityFinding]:
        """Every finding from every component, most severe first."""
        collected = [f for component in self.components for f in component.findings]
        return sorted(collected, key=lambda f: SEVERITY_ORDER.index(f.severity))

    def summary(self) -> dict[str, int]:
        counts = {severity.value: 0 for severity in SEVERITY_ORDER}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        counts["total_findings"] = sum(counts[s.value] for s in SEVERITY_ORDER)
        return counts

    def to_document(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "components": [component.to_document() for component in self.components],
            "findings": [finding.to_document() for finding in self.findings],
            "summary": self.summary(),
            "engine_metadata": self.engine_metadata,
            "error": self.error,
        }


def derive_run_status(components: list[ComponentResult]) -> RunStatus:
    """Roll component outcomes up into a run status.

    Findings never influence this: a target riddled with vulnerabilities
    still produces a ``completed`` run, because the engine did its job. Only
    a scanner that was asked to run and could not makes the run ``failed``.
    """
    if any(component.status is ComponentStatus.FAILED for component in components):
        return RunStatus.FAILED
    return RunStatus.COMPLETED
