"""Phase 6 engine tests: deterministic correlation and prioritization.

Pure functions over plain evidence dicts - no database, no network, no model.
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

import pytest

from app.engines.correlation.correlator import (
    EvidenceOwnershipError,
    assign_reference_numbers,
    correlate,
    link_ai_findings,
)
from app.engines.correlation.keys import (
    CorrelationRule,
    correlation_key,
    normalize_endpoint,
    origin_of,
)
from app.engines.prioritization.issue_builder import build_group_fields, build_issue_fields
from app.engines.prioritization.scoring import (
    AI_CONFIDENCE_POINTS,
    PRIORITY_THRESHOLDS,
    SEVERITY_POINTS,
    AISupport,
    PriorityInputs,
    compute_priority,
    priority_for_score,
)

AID = "a" * 24
OTHER = "b" * 24


def ev(seq: int, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "evidence_id": f"e{seq:04d}",
        "assessment_id": AID,
        "sequence": seq,
        "source": "zap",
        "finding_type": "security",
        "category": "passive_scan",
        "title": "Some alert",
        "target_component": "GET http://app.test/",
        "status": "failed",
        "tool_severity": "medium",
        "evidence_payload": {},
    }
    base.update(fields)
    return base


def zap(seq: int, rule: str, title: str, url: str, severity: str = "medium", **payload) -> dict:
    return ev(
        seq,
        title=title,
        target_component=f"GET {url}",
        tool_severity=severity,
        status="observed" if severity == "informational" else "failed",
        evidence_payload={"rule_id": rule, **payload},
    )


def qa(seq: int, title: str, url: str = "http://app.test/", status: str = "failed", **kw) -> dict:
    return ev(
        seq,
        source="playwright",
        finding_type="qa",
        category=kw.pop("category", "functional"),
        title=title,
        target_component=url,
        status=status,
        tool_severity=None,
        **kw,
    )


# --- normalization -------------------------------------------------------------


def test_normalization_is_limited_and_explainable() -> None:
    assert normalize_endpoint("GET HTTP://App.Test/Path/") == "http://app.test/Path"
    assert normalize_endpoint("GET http://app.test/a?x=1#frag", keep_method=True) == (
        "GET http://app.test/a?x=1"
    )
    assert origin_of("GET http://App.test:3000/robots.txt") == "http://app.test:3000"
    assert origin_of("src/app.py") == "src/app.py"


# --- grouping --------------------------------------------------------------------


def test_same_scanner_rule_on_one_origin_is_one_group() -> None:
    evidence = [
        zap(0, "10099", "Suspicious Comments", "http://app.test/"),
        zap(1, "10099", "Suspicious Comments", "http://app.test/a.js"),
        zap(2, "10099", "Suspicious Comments", "http://app.test/b.js"),
    ]
    outcome = correlate(AID, evidence)
    assert len(outcome.groups) == 1
    group = outcome.groups[0]
    assert group.rule is CorrelationRule.SAME_SCANNER_RULE_AND_ORIGIN
    assert group.evidence_refs == ["EV-001", "EV-002", "EV-003"]
    assert "10099" in group.reason()


def test_different_origin_rule_title_or_parameter_splits_groups() -> None:
    evidence = [
        zap(0, "10099", "Suspicious Comments", "http://app.test/"),
        zap(1, "10099", "Suspicious Comments", "http://api.test/"),  # other origin
        zap(2, "10098", "Suspicious Comments", "http://app.test/"),  # other rule
        zap(3, "10099", "Other title", "http://app.test/"),  # other alert variant
        zap(4, "10099", "Suspicious Comments", "http://app.test/", parameter="q"),
    ]
    assert len(correlate(AID, evidence).groups) == 5


def test_missing_header_is_one_issue_across_scanners_on_the_same_origin() -> None:
    evidence = [
        zap(0, "10020", "Missing Anti-clickjacking Header", "http://app.test/"),
        zap(1, "10020", "Missing Anti-clickjacking Header", "http://app.test/x"),
        ev(
            2,
            source="api_probe",
            category="security_headers",
            title="Missing X-Frame-Options header",
            target_component="http://app.test",
            tool_severity="low",
            evidence_payload={"rule_id": "api-probe-missing-x-frame-options"},
        ),
    ]
    groups = correlate(AID, evidence).groups
    assert len(groups) == 1
    group = groups[0]
    assert group.rule is CorrelationRule.SAME_MISSING_HEADER_AND_ORIGIN
    assert group.sources == ["api_probe", "zap"]
    # The most severe reported severity, copied - not raised or invented.
    assert group.tool_severity == "medium"
    assert "x-frame-options" in group.reason()


def test_zap_header_rule_variant_that_is_not_a_missing_header_is_not_merged() -> None:
    evidence = [
        zap(0, "10020", "Missing Anti-clickjacking Header", "http://app.test/"),
        zap(1, "10020", "X-Frame-Options Defined via META", "http://app.test/"),
    ]
    rules = {g.rule for g in correlate(AID, evidence).groups}
    assert rules == {
        CorrelationRule.SAME_MISSING_HEADER_AND_ORIGIN,
        CorrelationRule.SAME_SCANNER_RULE_AND_ORIGIN,
    }


def test_security_without_rule_id_uses_the_normalized_identity_on_the_same_endpoint() -> None:
    evidence = [
        ev(0, source="semgrep", title="Hardcoded secret", target_component="src/a.py"),
        ev(1, source="semgrep", title="  hardcoded   SECRET ", target_component="src/a.py"),
        ev(2, source="semgrep", title="Hardcoded secret", target_component="src/b.py"),
    ]
    groups = correlate(AID, evidence).groups
    assert [len(g.members) for g in groups] == [2, 1]
    assert groups[0].rule is CorrelationRule.SAME_NORMALIZED_IDENTITY


def test_qa_duplicates_group_by_check_and_component() -> None:
    evidence = [
        qa(0, "Page Title"),
        qa(1, "Page Title", url="http://app.test"),  # same page, trailing slash
        qa(2, "Page Title", url="http://app.test/other"),
        qa(3, "Failed network request", url="GET http://app.test/api", status="observed",
           category="network"),
        qa(4, "Failed network request", url="POST http://app.test/api", status="observed",
           category="network"),
    ]
    groups = correlate(AID, evidence).groups
    assert [len(g.members) for g in groups] == [2, 1, 1, 1]
    assert all(g.rule is CorrelationRule.SAME_QA_CHECK_AND_COMPONENT for g in groups)


def test_qa_and_security_are_never_merged_even_with_identical_text() -> None:
    evidence = [
        qa(0, "Missing X-Frame-Options header", url="http://app.test", category="security_headers"),
        ev(1, source="api_probe", category="security_headers",
           title="Missing X-Frame-Options header", target_component="http://app.test",
           evidence_payload={"rule_id": "api-probe-missing-x-frame-options"}),
    ]
    groups = correlate(AID, evidence).groups
    assert len(groups) == 2
    assert {g.finding_type for g in groups} == {"qa", "security"}


def test_passed_and_skipped_evidence_form_no_issue() -> None:
    evidence = [qa(0, "Page Title", status="passed"), qa(1, "DOM", status="skipped"),
                qa(2, "Reachability", status="error")]
    outcome = correlate(AID, evidence)
    assert outcome.evidence_total == 3
    assert outcome.evidence_considered == 1
    assert outcome.evidence_excluded == {"passed": 1, "skipped": 1}


def test_correlation_is_deterministic_regardless_of_input_order() -> None:
    evidence = [
        zap(i, "10020" if i % 2 else "10038",
            "Missing Anti-clickjacking Header" if i % 2 else "CSP Header Not Set",
            f"http://app.test/{i}")
        for i in range(12)
    ] + [qa(12, "Page Title")]
    first = correlate(AID, evidence)
    shuffled = list(evidence)
    random.Random(7).shuffle(shuffled)
    second = correlate(AID, shuffled)
    assert [g.group_key for g in first.groups] == [g.group_key for g in second.groups]
    assert [g.evidence_ids for g in first.groups] == [g.evidence_ids for g in second.groups]


def test_evidence_from_another_assessment_is_rejected() -> None:
    evidence = [zap(0, "10099", "X", "http://app.test/"), {**zap(1, "10099", "X", "http://app.test/"), "assessment_id": OTHER}]
    with pytest.raises(EvidenceOwnershipError):
        correlate(AID, evidence)


def test_duplicate_evidence_ids_are_rejected() -> None:
    record = zap(0, "10099", "X", "http://app.test/")
    with pytest.raises(EvidenceOwnershipError):
        correlate(AID, [record, dict(record)])


def test_reference_numbers_are_stable_and_never_reused() -> None:
    assert assign_reference_numbers(["a", "b"], {}) == {"a": 1, "b": 2}
    # Existing keys keep their numbers; a new key gets the next free one.
    assert assign_reference_numbers(["c", "a", "b"], {"a": 1, "b": 2}) == {"c": 3, "a": 1, "b": 2}
    assert assign_reference_numbers(["a"], {"a": 1, "gone": 7}) == {"a": 1}
    assert assign_reference_numbers(["n"], {"a": 1, "gone": 7}) == {"n": 8}


# --- AI findings as supporting metadata -------------------------------------------------


def test_ai_findings_link_only_by_type_and_owned_evidence() -> None:
    evidence = [zap(0, "10099", "X", "http://app.test/"), qa(1, "Page Title")]
    groups = correlate(AID, evidence).groups
    findings = [
        {"finding_id": "AI-F-001", "type": "security", "status": "supported",
         "confidence": "high", "title": "t", "evidence_ids": ["e0000"]},
        # Type mismatch: a QA finding citing security evidence is not linked.
        {"finding_id": "AI-F-002", "type": "qa", "status": "supported",
         "confidence": "high", "title": "t", "evidence_ids": ["e0000"]},
        # Foreign evidence is ignored and counted.
        {"finding_id": "AI-F-003", "type": "qa", "status": "supported",
         "confidence": "low", "title": "t", "evidence_ids": ["foreign-1", "e0001"]},
    ]
    result = link_ai_findings(groups, findings, {"e0000", "e0001"})
    by_type = {g.finding_type: result.links[g.group_key] for g in groups}
    assert [l.finding_id for l in by_type["security"]] == ["AI-F-001"]
    assert [l.finding_id for l in by_type["qa"]] == ["AI-F-003"]
    assert result.ignored_references == 1


# --- prioritization -----------------------------------------------------------------------


def inputs(**kw) -> PriorityInputs:
    base = dict(finding_type="security", tool_severity="medium", statuses=("failed",),
                sources=("zap",), evidence_count=1, distinct_endpoints=1)
    base.update(kw)
    return PriorityInputs(**base)


@pytest.mark.parametrize(
    ("severity", "expected"),
    [("high", "P1"), ("medium", "P2"), ("low", "P3"), ("informational", "P4")],
)
def test_single_observation_priority_follows_tool_severity(severity, expected) -> None:
    result = compute_priority(inputs(tool_severity=severity))
    assert result.priority == expected
    assert result.priority_score == SEVERITY_POINTS[severity]


def test_priority_is_deterministic_and_reasons_match_the_score() -> None:
    args = inputs(evidence_count=6, distinct_endpoints=4, sources=("api_probe", "zap"),
                  ai_support=(AISupport("AI-F-002", "supported", "medium"),))
    first, second = compute_priority(args), compute_priority(args)
    assert first == second
    assert first.priority_score == sum(f.points for f in first.factors)
    assert {f.factor for f in first.factors} == {
        "base", "spread", "repetition", "corroboration", "ai_support"
    }
    # Every factor is named in the reasons with its points.
    for factor in first.factors:
        assert any(f"(+{factor.points})" in r and factor.detail in r for r in first.reasons)
    assert f"Score {first.priority_score} gives {first.priority}" in first.reasons[-1]


def test_one_signal_never_promotes_but_agreeing_signals_can() -> None:
    assert compute_priority(inputs(distinct_endpoints=5, evidence_count=5)).priority == "P2"
    promoted = compute_priority(
        inputs(distinct_endpoints=5, evidence_count=5, sources=("api_probe", "zap"),
               ai_support=(AISupport("AI-F-001", "supported", "high"),))
    )
    assert promoted.priority == "P1"


def test_ai_insufficient_evidence_is_listed_but_not_counted() -> None:
    result = compute_priority(inputs(ai_support=(AISupport("AI-F-004", "insufficient_evidence", "high"),)))
    assert result.priority_score == SEVERITY_POINTS["medium"]
    assert result.ai_confidence is None
    assert any("AI-F-004" in r and "not counted" in r for r in result.reasons)


def test_qa_priority_uses_the_worst_status_not_an_invented_severity() -> None:
    assert compute_priority(inputs(finding_type="qa", tool_severity=None,
                                   statuses=("failed",))).priority == "P2"
    assert compute_priority(inputs(finding_type="qa", tool_severity=None,
                                   statuses=("observed",))).priority == "P3"


def test_thresholds_are_the_documented_ones() -> None:
    assert PRIORITY_THRESHOLDS == (("P1", 60), ("P2", 40), ("P3", 20))
    assert [priority_for_score(s) for s in (60, 59, 40, 39, 20, 19)] == [
        "P1", "P2", "P2", "P3", "P3", "P4"
    ]
    assert AI_CONFIDENCE_POINTS == {"high": 8, "medium": 5, "low": 2}


def test_issue_fields_keep_tool_severity_separate_from_priority() -> None:
    evidence = [zap(0, "10020", "Missing Anti-clickjacking Header", "http://app.test/", "low")]
    group = correlate(AID, evidence).groups[0]
    group_fields = build_group_fields(AID, group, 1)
    fields, priority = build_issue_fields(AID, group, 1, 1, [], None)
    assert group_fields["correlation_group_id"] == "CG-001"
    assert fields["issue_id"] == "ISSUE-001"
    assert fields["tool_severity"] == "low"
    assert fields["priority"] == priority.priority == "P3"
    assert fields["evidence_ids"] == ["e0000"]
    assert fields["ai_analysis_id"] is None and fields["ai_finding_ids"] == []
    assert "critical" not in str(fields).lower()


# --- guardrails -----------------------------------------------------------------------------

APP = Path(__file__).resolve().parents[1] / "app"
PHASE6_FILES = [
    *sorted((APP / "engines" / "correlation").glob("*.py")),
    *sorted((APP / "engines" / "prioritization").glob("*.py")),
    APP / "services" / "correlation_service.py",
    APP / "services" / "issue_service.py",
    APP / "api" / "routes" / "correlation.py",
    APP / "api" / "routes" / "issues.py",
]


@pytest.mark.parametrize("path", PHASE6_FILES, ids=lambda p: p.name)
def test_phase6_code_calls_no_model_tool_shell_or_network(path: Path) -> None:
    source = path.read_text(encoding="utf-8-sig")
    imports = "\n".join(re.findall(r"^\s*(?:from|import)\s+[\w.]+", source, re.MULTILINE))
    for banned in ("openai", "app.engines.ai", "subprocess", "httpx", "requests", "urllib.request",
                   "socket", "playwright", "zap_runner", "api_probes", "semgrep"):
        assert banned not in imports, f"{path.name} imports {banned}"
    for call in ("eval(", "exec(", "os.system(", "__import__(", " open("):
        assert call not in source, f"{path.name} uses {call}"


@pytest.mark.parametrize("path", PHASE6_FILES, ids=lambda p: p.name)
def test_phase6_code_is_target_independent(path: Path) -> None:
    source = path.read_text(encoding="utf-8-sig").lower()
    for marker in ("mini e-commerce", "mini-ecommerce", "localhost:3000", "localhost:4000", ":5000"):
        assert marker not in source, f"{path.name} mentions {marker}"
