"""From a stored retest specification to a scoped execution plan.

The plan names one existing engine and the smallest part of it that can
re-run the specified checks:

* ``security_rescan`` -> the security engine with only the scanners the
  checks came from (``zap`` / ``api_probes`` / ``semgrep``);
* ``qa_recheck``      -> the QA engine with only the named smoke-suite
  checks (plus the navigation step every check depends on).

Nothing else runs. A specification that names an unknown type, source or
check is not eligible - it is rejected, never widened into a larger scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.engines.orchestrator.normalizer import QA_CHECKS
from app.engines.remediation.models import RetestSpecification

#: Retest types this platform can execute (the Phase 8 vocabulary).
SUPPORTED_RETEST_TYPES = frozenset({"security_rescan", "qa_recheck"})

#: Evidence source -> security engine component that produces it.
SECURITY_SOURCE_COMPONENTS: dict[str, str] = {
    "zap": "zap",
    "api_probe": "api_probes",
    "semgrep": "semgrep",
}

#: QA observations are produced by these collection checks of the suite.
QA_CATEGORY_CHECKS: dict[str, str] = {
    "client_errors": "Console Error Collection",
    "network": "Network Failure Collection",
}

#: The generic smoke suite's check names (kept in step with the suite by a
#: Phase 4 test on QA_CHECKS).
QA_SUITE_CHECKS = frozenset(QA_CHECKS)


class RetestNotEligibleError(ValueError):
    """The stored specification cannot be executed as specified (409)."""


@dataclass(frozen=True)
class RetestPlan:
    engine: Literal["qa", "security"]
    #: Security scanners to run (engine == "security").
    components: frozenset[str] = frozenset()
    #: Smoke-suite checks to run (engine == "qa").
    qa_checks: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "components": sorted(self.components),
            "qa_checks": list(self.qa_checks),
        }


def qa_check_name(check: dict[str, Any] | Any, category: str | None) -> str:
    """The smoke-suite check that produced a QA evidence record."""
    title = check["title"] if isinstance(check, dict) else check.title
    if title in QA_SUITE_CHECKS:
        return title
    if category in QA_CATEGORY_CHECKS:
        return QA_CATEGORY_CHECKS[category]
    raise RetestNotEligibleError(
        f"QA check {title!r} is not part of the smoke suite this platform can re-run."
    )


def plan_retest(spec: RetestSpecification, categories: dict[str, str | None]) -> RetestPlan:
    """``categories`` maps each check's evidence_id to its stored evidence category."""
    if spec.retest_type not in SUPPORTED_RETEST_TYPES:
        raise RetestNotEligibleError(f"Unsupported retest type {spec.retest_type!r}.")
    if not spec.checks:
        raise RetestNotEligibleError("The retest specification names no checks.")

    if spec.retest_type == "security_rescan":
        if spec.pass_condition != "finding_absent":
            raise RetestNotEligibleError("A security rescan can only pass on 'finding_absent'.")
        components = set()
        for check in spec.checks:
            if check.finding_type != "security" or check.source not in SECURITY_SOURCE_COMPONENTS:
                raise RetestNotEligibleError(
                    f"Check {check.evidence_ref} ({check.source}) is not a security scanner check."
                )
            components.add(SECURITY_SOURCE_COMPONENTS[check.source])
        return RetestPlan(engine="security", components=frozenset(components))

    names: list[str] = []
    for check in spec.checks:
        if check.finding_type != "qa" or check.source != "playwright":
            raise RetestNotEligibleError(
                f"Check {check.evidence_ref} ({check.source}) is not a QA engine check."
            )
        name = qa_check_name(check, categories.get(check.evidence_id))
        if name not in names:
            names.append(name)
    return RetestPlan(engine="qa", qa_checks=tuple(names))
