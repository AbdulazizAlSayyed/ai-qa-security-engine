"""The priority model: every weight and threshold lives here, nowhere else.

Priority is a *derived* ranking of correlated issues. It is not a severity:
``tool_severity`` stays exactly what the scanner reported, and there is no
``critical``. The score is a sum of named factors, each computed from stored
structured data, so any issue's score can be recomputed by hand:

    priority_score = base + spread + repetition + corroboration + ai_support

``base``
    Security: the most severe tool severity among the issue's evidence
    (high 60, medium 40, low 20, informational 0).
    QA (no tool severity exists): the worst evidence status - a failed check
    40, a check that could not complete (``error``) 20, an observation such
    as a console error or failed request 20.
``spread``
    +3 for each additional distinct endpoint/component, at most +9.
``repetition``
    +2 for each additional observation on an already-counted endpoint,
    at most +4.
``corroboration``
    +8 when two or more different sources (e.g. ``zap`` and ``api_probe``)
    report the issue.
``ai_support``
    Only when a *completed* AI analysis has a ``supported`` finding that
    cites the issue's evidence: +8 for high confidence, +5 medium, +2 low
    (the highest linked finding counts once). ``insufficient_evidence``
    findings are listed but add nothing.

Priority level from the score: P1 >= 60, P2 >= 40, P3 >= 20, otherwise P4.
The supporting factors can add at most 29 points, so an issue moves up one
level only when several independent signals agree; a single observation
stays at the level its tool severity (or QA status) sets.

Factors that do not exist in the data - business criticality of a target,
exploitability, asset value - are not used and never implied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bump when any weight, threshold or factor changes.
PRIORITY_MODEL_VERSION = "1.0"

SEVERITY_POINTS: dict[str, int] = {"high": 60, "medium": 40, "low": 20, "informational": 0}
#: QA evidence carries no tool severity; its status is the only signal.
QA_STATUS_POINTS: dict[str, int] = {"failed": 40, "error": 20, "observed": 20}
QA_STATUS_ORDER: tuple[str, ...] = ("failed", "error", "observed")

SPREAD_POINTS_PER_EXTRA_ENDPOINT = 3
SPREAD_MAX_POINTS = 9
REPEAT_POINTS_PER_EXTRA_OBSERVATION = 2
REPEAT_MAX_POINTS = 4
CORROBORATION_POINTS = 8
CORROBORATION_MIN_SOURCES = 2
AI_CONFIDENCE_POINTS: dict[str, int] = {"high": 8, "medium": 5, "low": 2}
AI_CONFIDENCE_ORDER: tuple[str, ...] = ("high", "medium", "low")

#: (level, minimum score), checked in order.
PRIORITY_THRESHOLDS: tuple[tuple[str, int], ...] = (("P1", 60), ("P2", 40), ("P3", 20))
LOWEST_PRIORITY = "P4"
PRIORITY_LEVELS: tuple[str, ...] = ("P1", "P2", "P3", "P4")


@dataclass(frozen=True)
class AISupport:
    """One AI finding linked to the issue (from a completed analysis)."""

    finding_id: str
    status: str  # supported | insufficient_evidence
    confidence: str  # high | medium | low


@dataclass(frozen=True)
class PriorityInputs:
    finding_type: str
    tool_severity: str | None
    statuses: tuple[str, ...]
    sources: tuple[str, ...]
    evidence_count: int
    distinct_endpoints: int
    ai_support: tuple[AISupport, ...] = ()


@dataclass(frozen=True)
class ScoreFactor:
    factor: str
    points: int
    detail: str


@dataclass(frozen=True)
class PriorityResult:
    priority: str
    priority_score: int
    factors: tuple[ScoreFactor, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)
    #: The strongest supporting AI confidence actually counted, if any.
    ai_confidence: str | None = None


def priority_for_score(score: int) -> str:
    for level, minimum in PRIORITY_THRESHOLDS:
        if score >= minimum:
            return level
    return LOWEST_PRIORITY


_QA_BASE_TEXT: dict[str, str] = {
    "failed": "QA check failed",
    "error": "QA check could not complete (error)",
    "observed": "QA observation recorded (console error or failed request)",
}


def _base(inputs: PriorityInputs) -> ScoreFactor:
    if inputs.finding_type == "security":
        severity = inputs.tool_severity
        if severity in SEVERITY_POINTS:
            return ScoreFactor(
                "base",
                SEVERITY_POINTS[severity],
                f"Security finding reported with {severity} tool severity",
            )
        return ScoreFactor("base", 0, "Security finding with no tool severity reported")
    for status in QA_STATUS_ORDER:
        if status in inputs.statuses:
            return ScoreFactor("base", QA_STATUS_POINTS[status], _QA_BASE_TEXT[status])
    return ScoreFactor("base", 0, "No failing QA status")


def compute_priority(inputs: PriorityInputs) -> PriorityResult:
    """Deterministic priority for one issue. Same inputs, same result."""
    factors: list[ScoreFactor] = [_base(inputs)]

    extra_endpoints = max(inputs.distinct_endpoints - 1, 0)
    if extra_endpoints:
        points = min(extra_endpoints * SPREAD_POINTS_PER_EXTRA_ENDPOINT, SPREAD_MAX_POINTS)
        factors.append(
            ScoreFactor(
                "spread",
                points,
                f"Reported on {inputs.distinct_endpoints} distinct endpoints/components",
            )
        )

    repeats = max(inputs.evidence_count - max(inputs.distinct_endpoints, 1), 0)
    if repeats:
        points = min(repeats * REPEAT_POINTS_PER_EXTRA_OBSERVATION, REPEAT_MAX_POINTS)
        factors.append(
            ScoreFactor(
                "repetition",
                points,
                f"Observed {repeats} more time{'' if repeats == 1 else 's'} on the same "
                "endpoints/components",
            )
        )

    sources = sorted(set(inputs.sources))
    if len(sources) >= CORROBORATION_MIN_SOURCES:
        factors.append(
            ScoreFactor(
                "corroboration",
                CORROBORATION_POINTS,
                f"Reported independently by {len(sources)} sources ({', '.join(sources)})",
            )
        )

    counted: AISupport | None = None
    supported = [s for s in inputs.ai_support if s.status == "supported"]
    for level in AI_CONFIDENCE_ORDER:
        match = next(
            (s for s in sorted(supported, key=lambda s: s.finding_id) if s.confidence == level),
            None,
        )
        if match:
            counted = match
            break
    if counted:
        factors.append(
            ScoreFactor(
                "ai_support",
                AI_CONFIDENCE_POINTS[counted.confidence],
                f"Completed AI analysis supports it with {counted.confidence} confidence "
                f"({counted.finding_id})",
            )
        )

    score = sum(factor.points for factor in factors)
    priority = priority_for_score(score)

    reasons = [f"{factor.detail} (+{factor.points})" for factor in factors]
    insufficient = sorted(s.finding_id for s in inputs.ai_support if s.status != "supported")
    if insufficient:
        reasons.append(
            f"AI finding(s) {', '.join(insufficient)} marked the evidence insufficient; "
            "not counted (+0)"
        )
    thresholds = ", ".join(f"{level} >= {minimum}" for level, minimum in PRIORITY_THRESHOLDS)
    reasons.append(f"Score {score} gives {priority} ({thresholds}, otherwise {LOWEST_PRIORITY})")

    return PriorityResult(
        priority=priority,
        priority_score=score,
        factors=tuple(factors),
        reasons=tuple(reasons),
        ai_confidence=counted.confidence if counted else None,
    )
