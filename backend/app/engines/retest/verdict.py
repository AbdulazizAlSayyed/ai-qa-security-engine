"""Deterministic PASS / FAIL from a scoped engine run.

Two questions, kept apart:

1. **Did the retest execute?** (:func:`execution_problem`) - the planned
   scanners completed / the planned QA checks produced a result. If not,
   the retest *failed to execute* and has no verdict. A scanner that could
   not run is never read as "the finding is gone".
2. **What did it conclude?** (:func:`evaluate`), from the stored
   ``pass_condition``:

   * ``finding_absent`` - FAIL when any new actionable result (failed /
     error / observed, the Phase 6 rule) produces the same Phase 6
     correlation key as the issue (``match_key``); otherwise PASS.
   * ``check_passes``   - PASS when every specified QA check now reports
     ``passed``; FAIL when any of them reports anything else.

No model is consulted and nothing is re-scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.engines.correlation.correlator import ACTIONABLE_STATUSES
from app.engines.correlation.keys import correlation_key
from app.engines.remediation.models import RetestSpecification
from app.engines.retest.plan import RetestPlan

Verdict = Literal["PASS", "FAIL"]


@dataclass
class VerdictResult:
    verdict: Verdict
    reason: str
    results_evaluated: int
    #: New results that decided the verdict (matching findings, or the checks judged).
    observations: list[dict[str, Any]] = field(default_factory=list)


def execution_problem(plan: RetestPlan, run: dict[str, Any]) -> str | None:
    """Why the scoped run cannot be judged, or None when it executed as planned."""
    if plan.engine == "security":
        if run.get("error") or run.get("status") == "error":
            return "The security engine could not execute."
        components = {str(c.get("name")): c for c in run.get("components") or []}
        for name in sorted(plan.components):
            component = components.get(name)
            if component is None:
                return f"Scanner {name!r} did not report a result."
            if component.get("status") != "completed":
                return f"Scanner {name!r} did not complete (status {component.get('status')!r})."
        return None

    if run.get("error") or run.get("status") == "error":
        return "The QA engine could not execute."
    executed = {str(test.get("name")) for test in run.get("tests") or []}
    missing = [name for name in plan.qa_checks if name not in executed]
    if missing:
        return f"QA check(s) {', '.join(missing)} produced no result."
    return None


def _observation(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": evidence.get("source"),
        "finding_type": evidence.get("finding_type"),
        "title": evidence.get("title"),
        "target_component": evidence.get("target_component"),
        "status": evidence.get("status"),
        "tool_severity": evidence.get("tool_severity"),
        "correlation_key": correlation_key(evidence).group_key,
        "source_run_id": evidence.get("source_run_id"),
        "source_finding_id": evidence.get("source_finding_id"),
    }


def evaluate(spec: RetestSpecification, plan: RetestPlan, new_evidence: list[dict[str, Any]]) -> VerdictResult:
    """Judge normalized results of a run that :func:`execution_problem` accepted."""
    finding_type = "security" if plan.engine == "security" else "qa"
    relevant = [e for e in new_evidence if e.get("finding_type") == finding_type]

    if spec.pass_condition == "finding_absent":
        matches = [
            e
            for e in relevant
            if e.get("status") in ACTIONABLE_STATUSES
            and correlation_key(e).group_key == spec.match_key
        ]
        if matches:
            return VerdictResult(
                verdict="FAIL",
                reason=f"{len(matches)} new result(s) match the issue's correlation key; the condition is still present.",
                results_evaluated=len(relevant),
                observations=[_observation(e) for e in matches],
            )
        return VerdictResult(
            verdict="PASS",
            reason="No new result matches the issue's correlation key; the condition was not observed.",
            results_evaluated=len(relevant),
        )

    judged: list[dict[str, Any]] = []
    failing: list[dict[str, Any]] = []
    for check in spec.checks:
        results = [
            e for e in relevant if e.get("source") == check.source and e.get("title") == check.title
        ]
        judged.extend(results)
        failing.extend(e for e in results if e.get("status") != "passed")
    if failing or not judged:
        return VerdictResult(
            verdict="FAIL",
            reason=(
                f"{len(failing)} specified QA check result(s) did not pass."
                if failing
                else "The specified QA check reported no passing result."
            ),
            results_evaluated=len(relevant),
            observations=[_observation(e) for e in (failing or judged)],
        )
    return VerdictResult(
        verdict="PASS",
        reason=f"All {len(judged)} specified QA check result(s) passed.",
        results_evaluated=len(relevant),
        observations=[_observation(e) for e in judged],
    )
