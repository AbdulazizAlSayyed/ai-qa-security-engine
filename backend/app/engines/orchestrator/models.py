"""Assessment lifecycle types.

An *assessment* is one pass of the whole pipeline against a target: run the
QA engine, run the security engine, then normalize everything both produced
into a single evidence set.

The orchestrator owns sequencing and state. It deliberately owns no
judgement: it never decides whether a vulnerability is real, never rates
severity, and never reinterprets a scanner's output. Phase 5's AI layer is
what reads the evidence this produces.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AssessmentState(str, Enum):
    """Lifecycle states, in the order the orchestrator moves through them."""

    CREATED = "created"
    RUNNING = "running"
    QA_RUNNING = "qa_running"
    SECURITY_RUNNING = "security_running"
    NORMALIZING = "normalizing"
    #: Phase 5: an explicitly requested AI analysis of a completed
    #: assessment is running. Entered only from COMPLETED and always returns
    #: to it; the pipeline itself never enters this state.
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


#: Terminal states.
FINAL_STATES = frozenset({AssessmentState.COMPLETED, AssessmentState.FAILED})


class StageStatus(str, Enum):
    """Whether an engine stage *executed* - never whether the target passed.

    ``completed`` means the engine ran and produced a run, however many
    tests failed or findings it reported. ``failed`` means the engine could
    not execute at all (the service raised, or the run records that the
    engine itself broke). The tool's own verdict is kept separately, in
    ``qa_run_status`` / ``security_run_status``.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvidenceType(str, Enum):
    QA = "qa"
    SECURITY = "security"


class EvidenceStatus(str, Enum):
    """What the tool reported, carried through without reinterpretation."""

    #: A QA check held.
    PASSED = "passed"
    #: A QA check did not hold, or a scanner reported a finding.
    FAILED = "failed"
    #: The engine explicitly reported the check as not run.
    SKIPPED = "skipped"
    #: The check was attempted but could not execute - a fact about the
    #: engine, not the target.
    ERROR = "error"
    #: Recorded but not asserted on (console errors, network failures the
    #: browser saw). Later phases decide what they mean.
    OBSERVED = "observed"


@dataclass
class StateTransition:
    """One step of the lifecycle: which state, when, and why."""

    state: AssessmentState
    timestamp: datetime
    message: str | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "timestamp": self.timestamp,
            "message": self.message,
        }


@dataclass
class Evidence:
    """One normalized piece of evidence, whatever tool produced it.

    The common shape the AI layer will consume, so QA results and security
    findings become comparable without either being distorted. It points
    back at its origin (``source_run_id`` + ``source_finding_id``) instead of
    copying the tool's full output, which stays in ``qa_runs`` /
    ``security_runs``.
    """

    source: str
    finding_type: EvidenceType
    category: str
    #: The tool's own name for what it checked or found, verbatim.
    title: str
    target_component: str
    status: EvidenceStatus
    timestamp: datetime
    evidence_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    assessment_id: str | None = None
    #: Position in the order the normalizer emitted, for stable display.
    sequence: int = 0
    expected: str | None = None
    actual: str | None = None
    #: The scanner's severity as Phase 3 normalized it. Never assigned here.
    tool_severity: str | None = None
    source_run_id: str | None = None
    #: Where in the source run this came from: a scanner finding id, or a
    #: path such as ``tests[2]`` into the raw QA run.
    source_finding_id: str | None = None
    #: Compact, tool-specific fields. Not the whole raw payload.
    evidence_payload: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "assessment_id": self.assessment_id,
            "sequence": self.sequence,
            "source": self.source,
            "finding_type": self.finding_type.value,
            "category": self.category,
            "title": self.title,
            "target_component": self.target_component,
            "status": self.status.value,
            "expected": self.expected,
            "actual": self.actual,
            "tool_severity": self.tool_severity,
            "source_run_id": self.source_run_id,
            "source_finding_id": self.source_finding_id,
            "evidence_payload": self.evidence_payload,
            "timestamp": self.timestamp,
        }
