"""Engine-level tests for the security engine.

Everything here is deterministic and offline: scanners are faked, so the
suite never requires ZAP, Semgrep or a live target. The real-scanner paths
are covered in ``test_security_api.py`` behind markers that skip themselves
when the tool is not present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.engines.security.api_probes import (
    PROBE_ORIGIN,
    probe_cors,
    probe_http_methods,
    probe_security_headers,
    probe_server_disclosure,
)
from app.engines.security.models import (
    ComponentResult,
    ComponentStatus,
    RunStatus,
    SecurityFinding,
    SecurityRunOutcome,
    Severity,
    derive_run_status,
)
from app.engines.security.semgrep_runner import (
    SemgrepConfig,
    normalize_semgrep_result,
    run_semgrep,
)
from app.engines.security.zap_runner import (
    ZapConfig,
    normalize_zap_alert,
    run_zap_baseline,
)

ALL_HEADERS = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'self'",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


# --- ZAP normalization -------------------------------------------------


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        ("High", Severity.HIGH),
        ("Medium", Severity.MEDIUM),
        ("Low", Severity.LOW),
        ("Informational", Severity.INFORMATIONAL),
        ("Info", Severity.INFORMATIONAL),
        ("", Severity.INFORMATIONAL),
        ("something unexpected", Severity.INFORMATIONAL),
    ],
)
def test_zap_risk_is_normalized_into_our_severity_vocabulary(risk, expected) -> None:
    finding = normalize_zap_alert({"alert": "X", "risk": risk})
    assert finding.severity is expected


def test_zap_compound_risk_uses_the_leading_word() -> None:
    """ZAP sometimes writes 'Low (Medium)' meaning risk (confidence)."""
    assert normalize_zap_alert({"alert": "X", "risk": "Low (Medium)"}).severity is Severity.LOW


def test_zap_alert_fields_are_carried_across() -> None:
    finding = normalize_zap_alert(
        {
            "alert": "Content Security Policy Header Not Set",
            "risk": "Medium",
            "confidence": "High",
            "url": "http://target.test/",
            "method": "GET",
            "param": "q",
            "evidence": "<html>",
            "description": "No CSP",
            "solution": "Set one",
            "reference": "https://example.invalid/csp",
            "cweid": "693",
            "wascid": "15",
            "pluginId": "10038",
        }
    )

    assert finding.source == "zap"
    assert finding.name == "Content Security Policy Header Not Set"
    assert finding.rule_id == "10038"
    assert finding.confidence == "high"
    assert finding.url == "http://target.test/"
    assert finding.parameter == "q"
    assert finding.cwe == "693"
    assert finding.wasc == "15"
    # Nothing is thrown away.
    assert finding.raw["risk"] == "Medium"


@pytest.mark.parametrize("unmapped", ["0", "-1"])
def test_zap_unmapped_cwe_and_wasc_become_null(unmapped: str) -> None:
    finding = normalize_zap_alert({"alert": "X", "risk": "Low", "cweid": unmapped, "wascid": unmapped})
    assert finding.cwe is None
    assert finding.wasc is None


def test_zap_alert_without_a_name_still_normalizes() -> None:
    assert normalize_zap_alert({"risk": "Low"}).name == "Unnamed ZAP alert"


# --- security headers --------------------------------------------------


def test_all_headers_present_produces_no_findings() -> None:
    assert probe_security_headers("http://t/", ALL_HEADERS, is_https=False) == []


def test_each_missing_header_is_reported_once() -> None:
    findings = probe_security_headers("http://t/", {}, is_https=False)
    rule_ids = {f.rule_id for f in findings}
    assert rule_ids == {
        "api-probe-missing-x-content-type-options",
        "api-probe-missing-content-security-policy",
        "api-probe-missing-x-frame-options",
        "api-probe-missing-referrer-policy",
    }


def test_missing_headers_are_scored_conservatively() -> None:
    """None of these is a breach; calling them one trains people to ignore reports."""
    by_rule = {f.rule_id: f for f in probe_security_headers("http://t/", {}, is_https=False)}
    assert by_rule["api-probe-missing-x-content-type-options"].severity is Severity.LOW
    assert by_rule["api-probe-missing-referrer-policy"].severity is Severity.INFORMATIONAL
    assert all(f.severity is not Severity.HIGH for f in by_rule.values())


def test_hsts_is_only_expected_over_https() -> None:
    over_http = probe_security_headers("http://t/", ALL_HEADERS, is_https=False)
    assert not any("hsts" in (f.rule_id or "") for f in over_http)

    over_https = probe_security_headers("https://t/", ALL_HEADERS, is_https=True)
    hsts = [f for f in over_https if "hsts" in (f.rule_id or "")]
    assert len(hsts) == 1
    assert hsts[0].severity is Severity.MEDIUM


def test_header_matching_is_case_insensitive() -> None:
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "x",
               "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}
    assert probe_security_headers("http://t/", headers, is_https=False) == []


# --- server disclosure -------------------------------------------------


def test_no_disclosure_headers_produces_no_findings() -> None:
    assert probe_server_disclosure("http://t/", {}) == []


def test_version_disclosure_outranks_bare_product_name() -> None:
    with_version = probe_server_disclosure("http://t/", {"Server": "nginx/1.25.3"})
    without_version = probe_server_disclosure("http://t/", {"Server": "nginx"})
    assert with_version[0].severity is Severity.LOW
    assert without_version[0].severity is Severity.INFORMATIONAL


def test_x_powered_by_is_reported() -> None:
    findings = probe_server_disclosure("http://t/", {"X-Powered-By": "Express"})
    assert len(findings) == 1
    assert "x-powered-by" in findings[0].evidence.lower()


# --- CORS --------------------------------------------------------------


def test_no_cors_header_produces_no_finding() -> None:
    assert probe_cors("http://t/", {}, PROBE_ORIGIN) == []


def test_reflected_origin_with_credentials_is_the_only_high() -> None:
    findings = probe_cors(
        "http://t/",
        {
            "access-control-allow-origin": PROBE_ORIGIN,
            "access-control-allow-credentials": "true",
        },
        PROBE_ORIGIN,
    )
    assert len(findings) == 1
    assert findings[0].severity is Severity.HIGH
    assert findings[0].cwe == "942"


def test_wildcard_with_credentials_is_high() -> None:
    findings = probe_cors(
        "http://t/",
        {"access-control-allow-origin": "*", "access-control-allow-credentials": "true"},
        PROBE_ORIGIN,
    )
    assert findings[0].severity is Severity.HIGH


def test_reflected_origin_without_credentials_is_medium() -> None:
    findings = probe_cors("http://t/", {"access-control-allow-origin": PROBE_ORIGIN}, PROBE_ORIGIN)
    assert findings[0].severity is Severity.MEDIUM


def test_bare_wildcard_is_only_low() -> None:
    findings = probe_cors("http://t/", {"access-control-allow-origin": "*"}, PROBE_ORIGIN)
    assert findings[0].severity is Severity.LOW


def test_a_specific_trusted_origin_is_not_a_finding() -> None:
    """Echoing one configured origin is correct behaviour, not a weakness."""
    findings = probe_cors(
        "http://t/",
        {
            "access-control-allow-origin": "https://app.example",
            "access-control-allow-credentials": "true",
        },
        PROBE_ORIGIN,
    )
    assert findings == []


# --- HTTP methods ------------------------------------------------------


def test_no_advertised_methods_produces_no_finding() -> None:
    assert probe_http_methods("http://t/", {}) == []


def test_trace_is_reported_as_medium() -> None:
    findings = probe_http_methods("http://t/", {"allow": "GET, POST, TRACE"})
    trace = [f for f in findings if f.rule_id == "api-probe-trace-enabled"]
    assert len(trace) == 1
    assert trace[0].severity is Severity.MEDIUM


def test_state_changing_methods_are_only_informational() -> None:
    """Normal for a REST API, and the engine never sends them."""
    findings = probe_http_methods("http://t/", {"allow": "GET, PUT, DELETE, PATCH"})
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFORMATIONAL
    assert findings[0].method == "OPTIONS"


def test_safe_methods_alone_produce_no_finding() -> None:
    assert probe_http_methods("http://t/", {"allow": "GET, HEAD, OPTIONS"}) == []


def test_cors_allow_methods_header_is_also_read() -> None:
    findings = probe_http_methods("http://t/", {"access-control-allow-methods": "GET,TRACE"})
    assert any(f.rule_id == "api-probe-trace-enabled" for f in findings)


# --- ZAP component behaviour -------------------------------------------


class FakeZapHttp:
    """Routes ZAP REST calls to canned payloads."""

    def __init__(self, payloads: dict[str, Any], fail_on: str | None = None) -> None:
        self.payloads = payloads
        self.fail_on = fail_on
        self.calls: list[str] = []

    def get(self, url: str, params: dict[str, Any] | None = None):
        path = url.split("8090", 1)[-1] if "8090" in url else url
        self.calls.append(path)
        if self.fail_on and self.fail_on in path:
            raise RuntimeError("connection refused")

        payload = next(
            (value for key, value in self.payloads.items() if key in path), {}
        )
        return _FakeResponse(payload)

    def close(self) -> None:  # pragma: no cover - parity with httpx.Client
        pass


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._payload


def _zap_payloads(alerts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "core/view/version": {"version": "2.17.0"},
        "core/action/accessUrl": {"Result": "OK"},
        "spider/action/scan": {"scan": "0"},
        "spider/view/status": {"status": "100"},
        "pscan/view/recordsToScan": {"recordsToScan": "0"},
        "core/view/alerts": {"alerts": alerts or []},
    }


def test_disabled_zap_is_skipped_not_failed() -> None:
    result = run_zap_baseline("http://t/", ZapConfig(enabled=False))
    assert result.status is ComponentStatus.SKIPPED
    assert result.enabled is False
    assert "disabled" in result.detail.lower()


def test_unreachable_zap_fails_with_actionable_advice() -> None:
    client = FakeZapHttp(_zap_payloads(), fail_on="core/view/version")
    result = run_zap_baseline("http://t/", ZapConfig(poll_interval_seconds=0.01), client=client)

    assert result.status is ComponentStatus.FAILED
    assert "not reachable" in result.detail
    # The message must tell the reader how to fix it.
    assert "ZAP_ENABLED=false" in result.detail


def test_successful_zap_scan_normalizes_alerts() -> None:
    alerts = [
        {"alert": "SQL Injection", "risk": "High", "url": "http://t/x", "pluginId": "40018"},
        {"alert": "CSP Not Set", "risk": "Medium", "url": "http://t/"},
    ]
    client = FakeZapHttp(_zap_payloads(alerts))
    result = run_zap_baseline("http://t/", ZapConfig(poll_interval_seconds=0.01), client=client)

    assert result.status is ComponentStatus.COMPLETED
    assert result.metadata["zap_version"] == "2.17.0"
    assert result.metadata["alert_count"] == 2
    assert [f.severity for f in result.findings] == [Severity.HIGH, Severity.MEDIUM]
    assert all(f.source == "zap" for f in result.findings)


def test_zap_scan_never_performs_an_active_scan() -> None:
    """Phase 3 is baseline only: no attack payloads are ever sent."""
    client = FakeZapHttp(_zap_payloads())
    run_zap_baseline("http://t/", ZapConfig(poll_interval_seconds=0.01), client=client)

    assert not any("ascan" in call for call in client.calls), (
        f"active scan endpoint was called: {client.calls}"
    )


def test_zap_spider_can_be_switched_off() -> None:
    client = FakeZapHttp(_zap_payloads())
    result = run_zap_baseline(
        "http://t/", ZapConfig(spider=False, poll_interval_seconds=0.01), client=client
    )
    assert not any("spider" in call for call in client.calls)
    assert result.metadata["spider_completed"] is False


# --- Semgrep -----------------------------------------------------------


def test_semgrep_disabled_is_skipped() -> None:
    result = run_semgrep("C:/whatever", SemgrepConfig(enabled=False))
    assert result.status is ComponentStatus.SKIPPED
    assert result.enabled is False


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_semgrep_without_a_source_path_is_skipped(empty) -> None:
    result = run_semgrep(empty, SemgrepConfig())
    assert result.status is ComponentStatus.SKIPPED
    assert "source_path" in result.detail


def test_semgrep_with_a_nonexistent_path_is_skipped(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = run_semgrep(str(missing), SemgrepConfig())
    assert result.status is ComponentStatus.SKIPPED
    assert "does not exist" in result.detail


def test_semgrep_not_installed_is_skipped_not_failed(tmp_path: Path) -> None:
    """Semgrep is optional; its absence must never fail a security run."""
    result = run_semgrep(str(tmp_path), SemgrepConfig(executable="definitely-not-a-real-binary"))
    assert result.status is ComponentStatus.SKIPPED
    assert "not installed" in result.detail


@pytest.mark.parametrize(
    ("semgrep_severity", "expected"),
    [
        ("ERROR", Severity.HIGH),
        ("WARNING", Severity.MEDIUM),
        ("INFO", Severity.INFORMATIONAL),
        ("unknown", Severity.INFORMATIONAL),
    ],
)
def test_semgrep_severity_mapping(semgrep_severity, expected) -> None:
    finding = normalize_semgrep_result(
        {"check_id": "rules.py.dangerous", "path": "a.py", "start": {"line": 3},
         "extra": {"severity": semgrep_severity, "message": "bad"}},
        "C:/src",
    )
    assert finding.severity is expected


def test_semgrep_result_points_at_code_not_a_url() -> None:
    finding = normalize_semgrep_result(
        {"check_id": "rules.js.eval-use", "path": "src/a.js", "start": {"line": 42},
         "extra": {"severity": "ERROR", "message": "eval", "lines": "eval(x)",
                   "metadata": {"cwe": ["CWE-95"], "references": ["https://x.invalid"]}}},
        "C:/src",
    )
    assert finding.url == "src/a.js:42"
    assert finding.name == "eval-use"
    assert finding.cwe == "CWE-95"
    assert finding.reference == "https://x.invalid"
    assert finding.source == "semgrep"


# --- run status roll-up ------------------------------------------------


def _component(status: ComponentStatus, findings: list[SecurityFinding] | None = None):
    return ComponentResult(name="x", status=status, findings=findings or [])


def test_all_completed_is_a_completed_run() -> None:
    assert derive_run_status([_component(ComponentStatus.COMPLETED)]) is RunStatus.COMPLETED


def test_skipped_components_do_not_spoil_a_run() -> None:
    components = [_component(ComponentStatus.COMPLETED), _component(ComponentStatus.SKIPPED)]
    assert derive_run_status(components) is RunStatus.COMPLETED


def test_a_failed_scanner_fails_the_run() -> None:
    components = [_component(ComponentStatus.COMPLETED), _component(ComponentStatus.FAILED)]
    assert derive_run_status(components) is RunStatus.FAILED


def test_findings_never_make_a_run_fail() -> None:
    """A vulnerable target is a completed assessment, not a broken one."""
    critical = SecurityFinding(source="zap", name="SQL Injection", severity=Severity.HIGH)
    components = [_component(ComponentStatus.COMPLETED, [critical])]
    assert derive_run_status(components) is RunStatus.COMPLETED


# --- summary -----------------------------------------------------------


def _outcome(findings: list[SecurityFinding]) -> SecurityRunOutcome:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return SecurityRunOutcome(
        status=RunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
        duration_ms=1,
        components=[_component(ComponentStatus.COMPLETED, findings)],
    )


def test_summary_counts_every_severity() -> None:
    findings = [
        SecurityFinding(source="zap", name="a", severity=Severity.HIGH),
        SecurityFinding(source="zap", name="b", severity=Severity.MEDIUM),
        SecurityFinding(source="api_probe", name="c", severity=Severity.LOW),
        SecurityFinding(source="api_probe", name="d", severity=Severity.LOW),
        SecurityFinding(source="semgrep", name="e", severity=Severity.INFORMATIONAL),
    ]
    summary = _outcome(findings).summary()
    assert summary == {
        "high": 1, "medium": 1, "low": 2, "informational": 1, "total_findings": 5,
    }


def test_empty_summary_is_all_zeroes() -> None:
    assert _outcome([]).summary()["total_findings"] == 0


def test_findings_are_returned_most_severe_first() -> None:
    findings = [
        SecurityFinding(source="s", name="info", severity=Severity.INFORMATIONAL),
        SecurityFinding(source="s", name="high", severity=Severity.HIGH),
        SecurityFinding(source="s", name="low", severity=Severity.LOW),
        SecurityFinding(source="s", name="medium", severity=Severity.MEDIUM),
    ]
    ordered = [f.name for f in _outcome(findings).findings]
    assert ordered == ["high", "medium", "low", "info"]


# --- guard rail --------------------------------------------------------


def test_security_engine_contains_no_target_specific_values() -> None:
    """The engine must never learn about one particular application."""
    import app.engines.security as security_package

    banned = [
        "mini e-commerce",
        "mini-ecommerce",
        "localhost:3000",
        "localhost:4000",
        "6aa9dc1a",
    ]
    engine_dir = Path(security_package.__file__).parent
    offenders: list[str] = []

    for path in sorted(engine_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        for needle in banned:
            if needle in source:
                offenders.append(f"{path.name}: {needle}")

    assert offenders == [], f"target-specific values leaked into the engine: {offenders}"


def test_engine_only_ever_names_safe_http_methods() -> None:
    """Destructive verbs may be *reported*, never *sent*."""
    from app.engines.security import api_probes

    source = Path(api_probes.__file__).read_text(encoding="utf-8")
    # The only request calls in the module.
    assert 'client.get(' in source
    assert 'client.request(\n                    "OPTIONS"' in source
    for verb in ('client.delete(', 'client.put(', 'client.patch(', 'client.post('):
        assert verb not in source, f"probe module must not call {verb}"
