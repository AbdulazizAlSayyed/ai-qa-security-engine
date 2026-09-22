"""Evidence normalization.

Turns the raw output of two very different engines into one comparable
shape. This layer is deliberately mechanical: it reshapes and labels, and it
never decides severity, never merges duplicates, never correlates and never
concludes anything.

Three rules hold throughout:

* **Nothing is invented.** ``expected`` is filled only where the check that
  ran genuinely asserted something. A scanner alert has no meaningful
  expected value, so security evidence carries ``expected=None``.
* **Nothing is reinterpreted.** A QA failure stays a QA failure with no
  severity attached; a ZAP ``medium`` stays ``medium``.
* **Everything is traceable.** Each record names the assessment it belongs
  to, the raw run it came from, and where inside that run it came from.

Raw runs stay where they are. ``qa_runs`` and ``security_runs`` remain the
untouched record of what each tool actually emitted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.engines.orchestrator.models import Evidence, EvidenceStatus, EvidenceType

# --- QA ----------------------------------------------------------------

#: What each check of the generic smoke suite asserts, restated from
#: ``app.engines.qa.smoke_suite`` so the normalizer never has to guess. A
#: test keeps this table in step with the suite. The two collection checks
#: assert nothing about the target - they only gather observations - so
#: their expectation is ``None``.
QA_CHECKS: dict[str, tuple[str, str | None]] = {
    "Application Reachability": ("availability", "HTTP status below 400"),
    "Page Title": ("functional", "a non-empty page title"),
    "DOM Availability": ("functional", "a <body> element and non-empty markup"),
    "Console Error Collection": ("client_errors", None),
    "Network Failure Collection": ("network", None),
}

#: Tests from a suite this table does not know - a future target-specific
#: suite, say - are still normalized, just without an expectation.
DEFAULT_QA_CATEGORY = "functional"

_QA_STATUS: dict[str, EvidenceStatus] = {
    "passed": EvidenceStatus.PASSED,
    "failed": EvidenceStatus.FAILED,
    "skipped": EvidenceStatus.SKIPPED,
    "error": EvidenceStatus.ERROR,
}


def _reachability_actual(test: dict[str, Any], details: dict[str, Any]) -> str | None:
    if details.get("http_status") is not None:
        return f"HTTP {details['http_status']}"
    return details.get("note")


def _title_actual(test: dict[str, Any], details: dict[str, Any]) -> str | None:
    if test.get("title"):
        return str(test["title"])
    if "title_length" in details:
        return f"title of {details['title_length']} characters"
    return None


def _dom_actual(test: dict[str, Any], details: dict[str, Any]) -> str | None:
    parts = []
    if "html_length" in details:
        parts.append(f"{details['html_length']} characters of markup")
    if "element_count" in details:
        parts.append(f"{details['element_count']} elements")
    return ", ".join(parts) or None


def _count_actual(noun: str) -> Callable[[dict[str, Any], dict[str, Any]], str | None]:
    def actual(test: dict[str, Any], details: dict[str, Any]) -> str | None:
        if "count" not in details:
            return None
        count = details["count"]
        return f"{count} {noun}{'' if count == 1 else 's'} captured"

    return actual


#: How to read each check's recorded details back out as an observed value.
#: Pure reformatting of what the check stored.
_QA_ACTUAL: dict[str, Callable[[dict[str, Any], dict[str, Any]], str | None]] = {
    "Application Reachability": _reachability_actual,
    "Page Title": _title_actual,
    "DOM Availability": _dom_actual,
    "Console Error Collection": _count_actual("console error"),
    "Network Failure Collection": _count_actual("failed request"),
}


def _run_timestamp(run: dict[str, Any]) -> datetime:
    """When the tool reported: the run's finish, else its start."""
    for key in ("finished_at", "started_at"):
        value = run.get(key)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def _truncate(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit] if text else None


def normalize_qa_run(qa_run: dict[str, Any]) -> list[Evidence]:
    """Reshape one stored QA run into evidence records."""
    run_id = qa_run.get("id")
    base_url = qa_run.get("target_base_url", "")
    timestamp = _run_timestamp(qa_run)
    evidence: list[Evidence] = []

    for index, test in enumerate(qa_run.get("tests", [])):
        name = str(test.get("name", ""))
        raw_status = str(test.get("status", ""))
        status = _QA_STATUS.get(raw_status)
        if status is None:
            # Unknown vocabulary is carried through as an engine-side fact
            # rather than guessed into passed/failed.
            status = EvidenceStatus.ERROR

        category, expected = QA_CHECKS.get(name, (DEFAULT_QA_CATEGORY, None))
        details = test.get("details") or {}

        if status in (EvidenceStatus.FAILED, EvidenceStatus.ERROR) and test.get("error"):
            actual = _truncate(test["error"])
        elif name in _QA_ACTUAL:
            actual = _truncate(_QA_ACTUAL[name](test, details))
        else:
            actual = None

        evidence.append(
            Evidence(
                source="playwright",
                finding_type=EvidenceType.QA,
                category=category,
                title=name or "QA check",
                target_component=str(test.get("url") or base_url),
                status=status,
                expected=expected,
                actual=actual,
                # QA assertions carry no severity. Assigning one would be
                # analysis, which is Phase 5's job.
                tool_severity=None,
                source_run_id=run_id,
                source_finding_id=f"tests[{index}]",
                timestamp=timestamp,
                evidence_payload={
                    "name": test.get("name"),
                    "status": test.get("status"),
                    "duration_ms": test.get("duration_ms"),
                    "url": test.get("url"),
                    "error": test.get("error"),
                    "details": details,
                },
            )
        )

    for index, console_error in enumerate(qa_run.get("console_errors", [])):
        evidence.append(
            Evidence(
                source="playwright",
                finding_type=EvidenceType.QA,
                category="client_errors",
                title=f"Browser console {console_error.get('type', 'error')}",
                target_component=str(console_error.get("location") or base_url),
                status=EvidenceStatus.OBSERVED,
                actual=_truncate(console_error.get("message", "")),
                source_run_id=run_id,
                source_finding_id=f"console_errors[{index}]",
                timestamp=timestamp,
                evidence_payload=dict(console_error),
            )
        )

    for index, failure in enumerate(qa_run.get("network_failures", [])):
        status_code = failure.get("status")
        evidence.append(
            Evidence(
                source="playwright",
                finding_type=EvidenceType.QA,
                category="network",
                title="Failed network request",
                target_component=(
                    f"{failure.get('method', 'GET')} {failure.get('url', '')}".strip()
                ),
                status=EvidenceStatus.OBSERVED,
                actual=(
                    f"HTTP {status_code}"
                    if status_code
                    else _truncate(failure.get("failure"))
                ),
                source_run_id=run_id,
                source_finding_id=f"network_failures[{index}]",
                timestamp=timestamp,
                evidence_payload=dict(failure),
            )
        )

    return evidence


# --- security ------------------------------------------------------------

#: API probe rule prefixes -> the family of check that produced the finding.
#: The probe declared what it checks in its own rule id, so this is a label,
#: not a judgement.
_PROBE_CATEGORY_PREFIXES: list[tuple[str, str]] = [
    ("api-probe-missing-hsts", "transport_security"),
    ("api-probe-missing-", "security_headers"),
    ("api-probe-cors-", "cors"),
    ("api-probe-disclosure-", "information_disclosure"),
    ("api-probe-trace-enabled", "http_methods"),
    ("api-probe-state-changing-methods", "http_methods"),
]

#: Fields worth keeping next to a security finding. The long ones -
#: description, solution, references, the scanner's raw blob - stay in the
#: security run and are reachable through ``source_finding_id``.
_SECURITY_PAYLOAD_KEYS = (
    "rule_id",
    "name",
    "severity",
    "confidence",
    "cwe",
    "wasc",
    "method",
    "parameter",
    "url",
)


def security_category(source: str, rule_id: str | None) -> str:
    """Label a security finding by the family of check that produced it.

    Grouping findings from different tools by weakness class is correlation,
    which belongs to Phase 6 - so ZAP output is labelled by how it was found
    (a passive scan), not by what it might mean.
    """
    if source == "semgrep":
        return "static_analysis"
    if source == "zap":
        return "passive_scan"
    if source == "api_probe":
        for prefix, category in _PROBE_CATEGORY_PREFIXES:
            if rule_id and rule_id.startswith(prefix):
                return category
        return "api_probe"
    return "other"


def normalize_security_run(security_run: dict[str, Any]) -> list[Evidence]:
    """Reshape one stored security run into evidence records."""
    run_id = security_run.get("id")
    base_url = security_run.get("target_base_url", "")
    timestamp = _run_timestamp(security_run)
    evidence: list[Evidence] = []

    for finding in security_run.get("findings", []):
        # Keep the scanner's identity exactly: zap, api_probe and semgrep
        # never collapse into one generic source.
        source = str(finding.get("source") or "unknown")
        component = str(finding.get("url") or base_url)
        if finding.get("method"):
            component = f"{finding['method']} {component}"

        severity = str(finding["severity"]) if finding.get("severity") else None
        # A finding the scanner itself rates informational is output it
        # records without asserting a problem, so it is carried as observed.
        # Everything else the scanner reported means its check did not hold.
        # The severity itself is copied verbatim either way.
        status = (
            EvidenceStatus.OBSERVED
            if severity == "informational"
            else EvidenceStatus.FAILED
        )

        evidence.append(
            Evidence(
                source=source,
                finding_type=EvidenceType.SECURITY,
                category=security_category(source, finding.get("rule_id")),
                title=str(finding.get("name") or finding.get("rule_id") or "Security finding"),
                target_component=component,
                # Whether any of it matters is a later decision.
                status=status,
                # A scanner alert has no meaningful expected value. Writing
                # "secure" here would be fabricating evidence.
                expected=None,
                actual=_truncate(finding.get("evidence")),
                tool_severity=severity,
                source_run_id=run_id,
                source_finding_id=finding.get("id"),
                timestamp=timestamp,
                evidence_payload={
                    key: finding.get(key)
                    for key in _SECURITY_PAYLOAD_KEYS
                    if finding.get(key) is not None
                },
            )
        )

    return evidence


def security_coverage(security_run: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Which scanners ran, were skipped, or failed - and why.

    Kept beside the evidence rather than inside it: a scanner that could not
    run is a gap in coverage, not a fact about the target.
    """
    if not security_run:
        return []
    return [
        {
            "source": str(component.get("name", "")),
            "status": str(component.get("status", "")),
            "detail": component.get("detail"),
        }
        for component in security_run.get("components", [])
    ]


# --- assembly ------------------------------------------------------------


def normalize_assessment(
    assessment_id: str,
    qa_run: dict[str, Any] | None,
    security_run: dict[str, Any] | None,
) -> list[Evidence]:
    """All evidence for one assessment, in a stable order.

    QA first in suite order, then security most-severe-first (the order the
    security run already stores). A stage that produced no run contributes
    nothing - evidence is never created for work that did not happen.
    """
    evidence: list[Evidence] = []
    if qa_run:
        evidence.extend(normalize_qa_run(qa_run))
    if security_run:
        evidence.extend(normalize_security_run(security_run))

    for sequence, item in enumerate(evidence):
        item.assessment_id = assessment_id
        item.sequence = sequence
    return evidence


def summarise(
    qa_run: dict[str, Any] | None,
    security_run: dict[str, Any] | None,
    evidence_total: int,
) -> dict[str, Any]:
    """Deterministic counts, taken straight from the raw runs.

    ``total_findings`` is QA checks that failed plus security findings of
    every severity: the number of things a tool reported as not holding.
    """
    qa = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for test in (qa_run or {}).get("tests", []):
        qa["total"] += 1
        status = str(test.get("status", ""))
        if status in qa and status != "total":
            qa[status] += 1

    security = {"total": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}
    for finding in (security_run or {}).get("findings", []):
        security["total"] += 1
        severity = str(finding.get("severity", ""))
        if severity in security and severity != "total":
            security[severity] += 1

    return {
        "qa": qa,
        "security": security,
        "total_findings": qa["failed"] + security["total"],
        "evidence_total": evidence_total,
    }
