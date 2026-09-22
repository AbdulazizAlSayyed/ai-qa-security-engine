"""Phase 10 unit tests: traceability audit, assembly, HTML / PDF rendering,
secret handling and static guardrails. No database, no engines, no AI."""

from __future__ import annotations

import ast
import copy
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bson import ObjectId

from app.engines.reporting.assembler import REPORT_VERSION, assemble, fingerprint, retest_outcome
from app.engines.reporting.html_renderer import SECTIONS, render_html
from app.engines.reporting.pdf_renderer import render_pdf
from app.engines.reporting.redaction import find_leaks, known_secrets
from app.engines.reporting.traceability import TraceInputs, audit

T0 = datetime(2026, 9, 22, 10, 0, 0, tzinfo=timezone.utc)
APP = Path(__file__).resolve().parents[1] / "app"


def chain() -> TraceInputs:
    """A complete, consistent chain: target -> ... -> retests (plain dicts)."""
    aid, tid, qid, sid = (str(ObjectId()) for _ in range(4))
    ev = lambda seq, eid, **kw: {  # noqa: E731
        "_id": ObjectId(), "evidence_id": eid, "assessment_id": aid, "sequence": seq, "timestamp": T0, **kw}
    evidence = [
        ev(0, "e" * 31 + "0", source="playwright", finding_type="qa", category="page_title", title="Page Title",
           target_component="http://t.invalid/", status="failed", expected="a title", actual="(empty)",
           source_run_id=qid, source_finding_id="tests[0]", evidence_payload={"cookie": "should-not-appear"}),
        ev(1, "e" * 31 + "1", source="playwright", finding_type="qa", category="client_errors", title="Browser console error",
           target_component="http://t.invalid/app.js", status="observed", actual="TypeError x", source_run_id=qid,
           source_finding_id="console_errors[0]"),
        ev(2, "e" * 31 + "2", source="zap", finding_type="security", category="headers", title="CSP Header Not Set",
           target_component="http://t.invalid/", status="observed", tool_severity="medium", source_run_id=sid,
           source_finding_id="f-1"),
    ]
    assessment = {
        "_id": ObjectId(aid), "target_id": tid, "target_name": "Demo", "target_base_url": "http://t.invalid",
        "target_api_url": None, "target_type": "web_application", "status": "completed", "partial": False,
        "created_at": T0, "started_at": T0, "finished_at": T0, "duration_ms": 10,
        "qa_run_id": qid, "qa_status": "completed", "qa_run_status": "failed", "security_run_id": sid,
        "security_status": "completed", "security_run_status": "completed", "security_coverage": [
            {"source": "zap", "status": "completed", "detail": None},
            {"source": "authorization_probes", "status": "skipped", "detail": "No credentials registered."}],
        "summary": {"qa": {"total": 1, "passed": 0, "failed": 1, "skipped": 0, "error": 0},
                    "security": {"total": 1, "high": 0, "medium": 1, "low": 0, "informational": 0},
                    "total_findings": 2, "evidence_total": 3},
        "state_history": [{"state": s, "timestamp": T0} for s in
                          ("created", "running", "qa_running", "security_running", "normalizing", "completed")],
        "ai_analysis_status": "completed", "ai_analysis_id": "a" * 32,
        "correlation": {"status": "completed", "correlation_version": "1.0", "priority_model_version": "1.0", "completed_at": T0},
        "recommendation": {"status": "completed"},
    }
    analysis = {"_id": ObjectId(), "analysis_id": "a" * 32, "assessment_id": aid, "status": "completed", "provider": "fake",
                "model": "fake-model", "analysis_version": "1.0", "created_at": T0, "completed_at": T0,
                "evidence_ids": [e["evidence_id"] for e in evidence],
                "result": {"overall_assessment": "Two problems.", "evidence_gaps": [], "limitations": ["fake"],
                           "findings": [{"finding_id": "AI-F-001", "type": "security", "status": "supported", "title": "No CSP",
                                         "description": "d", "impact": "i", "confidence": "high", "tool_severity": "medium",
                                         "evidence_ids": [evidence[2]["evidence_id"]], "evidence_refs": ["EV-003"],
                                         "affected_components": ["http://t.invalid/"], "uncertainty": "u"}]}}
    group = {"_id": ObjectId(), "assessment_id": aid, "correlation_group_id": "CG-001", "group_number": 1,
             "group_key": "security|10038|csp|origin", "correlation_rule": "same_rule_same_component",
             "correlation_reason": "same rule", "finding_type": "security", "tool_severity": "medium",
             "evidence_ids": [evidence[2]["evidence_id"]], "evidence_refs": ["EV-003"]}
    issue = {"_id": ObjectId(), "assessment_id": aid, "issue_id": "ISSUE-001", "issue_number": 1, "correlation_group_id": "CG-001",
             "group_key": group["group_key"], "type": "security", "title": "CSP Header Not Set", "priority": "P2",
             "priority_score": 55, "priority_reasons": ["medium tool severity"], "priority_model_version": "1.0",
             "score_factors": [{"factor": "base", "points": 50, "detail": "medium"}, {"factor": "ai_support", "points": 5, "detail": "AI"}],
             "tool_severity": "medium", "confidence": "high", "affected_components": ["http://t.invalid/"],
             "correlation_rule": "same_rule_same_component", "evidence_ids": list(group["evidence_ids"]), "evidence_refs": ["EV-003"],
             "ai_analysis_id": "a" * 32, "ai_finding_ids": ["AI-F-001"]}
    check = {"evidence_id": evidence[2]["evidence_id"], "evidence_ref": "EV-003", "source": "zap", "finding_type": "security",
             "rule_id": "10038", "title": "CSP Header Not Set", "target_component": "http://t.invalid/", "baseline_status": "observed"}
    rec = {"_id": ObjectId(), "assessment_id": aid, "recommendation_id": "REC-001", "recommendation_number": 1,
           "ai_analysis_id": "a" * 32, "issue_id": "ISSUE-001", "related_issue_ids": [], "issue_priority": "P2",
           "type": "configuration_change", "title": "Add a CSP", "description": "Set Content-Security-Policy.",
           "rationale": "EV-003", "confidence": "high", "advisory_status": "advisory", "affected_components": ["http://t.invalid/"],
           "evidence_ids": [evidence[2]["evidence_id"]], "evidence_refs": ["EV-003"], "updated_at": T0,
           "retest": {"retest_type": "security_rescan", "scope": "origin", "target_id": tid, "target_component": "http://t.invalid/",
                      "issue_id": "ISSUE-001", "match_key": group["group_key"], "correlation_rule": "same_rule_same_component",
                      "pass_condition": "finding_absent", "checks": [check], "preconditions": [], "expected_result": "gone",
                      "pass_criteria": "absent", "fail_criteria": "present"}}
    new_run = str(ObjectId())
    base_retest = {"assessment_id": aid, "recommendation_id": "REC-001", "recommendation_ref": str(rec["_id"]), "issue_id": "ISSUE-001",
                   "type": "security_rescan", "scope": "origin", "target_component": "http://t.invalid/", "match_key": group["group_key"],
                   "pass_condition": "finding_absent", "checks": [check], "plan": {"engine": "security", "components": ["zap"], "qa_checks": []},
                   "started_at": T0, "completed_at": T0, "duration_ms": 5, "source_run_ids": [new_run],
                   "source_runs": [{"engine": "security", "run_id": new_run, "status": "completed"}]}
    retests = [
        {**base_retest, "_id": ObjectId(), "retest_id": "RETEST-001", "retest_number": 1, "status": "failed", "verdict": None,
         "error": {"category": "execution_failed", "message": "zap did not complete"}, "matched_evidence_ids": []},
        {**base_retest, "_id": ObjectId(), "retest_id": "RETEST-002", "retest_number": 2, "status": "completed", "verdict": "FAIL",
         "matched_evidence_ids": [evidence[2]["evidence_id"]], "matched_evidence_refs": ["EV-003"],
         "observations": [{"source": "zap", "status": "observed", "title": "CSP Header Not Set", "target_component": "http://t.invalid/",
                           "correlation_key": group["group_key"]}],
         "result_summary": {"engine": "security", "results_evaluated": 3, "matching_results": 1, "reason": "still present"}},
        {**base_retest, "_id": ObjectId(), "retest_id": "RETEST-003", "retest_number": 3, "status": "completed", "verdict": "PASS",
         "matched_evidence_ids": [], "result_summary": {"engine": "security", "results_evaluated": 2, "matching_results": 0, "reason": "gone"}},
    ]
    return TraceInputs(
        assessment=assessment,
        target={"_id": ObjectId(tid), "name": "Demo", "base_url": "http://t.invalid", "api_url": None, "type": "web_application", "enabled": True},
        qa_run={"_id": ObjectId(qid), "target_id": tid, "tests": [{"name": "Page Title", "status": "failed", "error": "no <title>"}],
                "console_errors": [{"type": "error", "message": "TypeError x"}], "network_failures": []},
        security_run={"_id": ObjectId(sid), "target_id": tid, "findings": [{"id": "f-1"}],
                      "components": [{"name": "zap", "enabled": True, "status": "completed", "findings": [{"id": "f-1"}]},
                                     {"name": "semgrep", "enabled": False, "status": "skipped", "detail": "Disabled.", "findings": []}]},
        evidence=evidence, analyses=[analysis], groups=[group], issues=[issue], recommendations=[rec], retests=retests,
        retest_runs={new_run: tid},
    )


def build(inputs: TraceInputs) -> dict:
    trace = audit(inputs)
    model = assemble(assessment=inputs.assessment, target=inputs.target, qa_run=inputs.qa_run, security_run=inputs.security_run,
                     evidence=inputs.evidence, analyses=inputs.analyses, groups=inputs.groups, issues=inputs.issues,
                     recommendations=inputs.recommendations, retests=inputs.retests, traceability=trace.as_dict())
    model["meta"].update({"report_id": "REPORT-001", "generated_at": "2026-09-22T10:00:00Z", "source_fingerprint": fingerprint(model)})
    return model


def problems(inputs: TraceInputs) -> set[str]:
    return {e.relationship for e in audit(inputs).errors}


# --- traceability ------------------------------------------------------------------------


def test_complete_chain_passes_and_every_relationship_is_checked() -> None:
    result = audit(chain())
    assert result.ok, result.errors
    for rel in ("assessment->target", "assessment->qa_run", "assessment->security_run", "evidence->assessment",
                "evidence->source_run", "evidence->source_finding", "ai_finding->evidence", "correlation_group->evidence",
                "issue->correlation_group", "issue->evidence", "issue->ai_finding", "recommendation->issue",
                "recommendation->ai_analysis", "recommendation->evidence", "retest->recommendation", "retest->issue",
                "retest->original_evidence", "retest->source_run"):
        assert result.checks.get(rel), rel


def test_optional_links_may_be_absent() -> None:
    inputs = chain()
    inputs.analyses, inputs.recommendations, inputs.retests, inputs.retest_runs = [], [], [], {}
    inputs.issues[0].update(ai_analysis_id=None, ai_finding_ids=[])
    assert audit(inputs).ok


def test_target_snapshot_suffices_when_target_was_removed() -> None:
    inputs = chain()
    inputs.target = None
    assert audit(inputs).ok
    inputs.assessment["target_base_url"] = None
    assert "assessment->target" in problems(inputs)


@pytest.mark.parametrize(
    ("mutate", "relationship"),
    [
        (lambda c: c.issues[0]["evidence_ids"].append("f" * 32), "issue->evidence"),
        (lambda c: c.groups[0]["evidence_ids"].append("f" * 32), "correlation_group->evidence"),
        (lambda c: c.analyses[0]["result"]["findings"][0]["evidence_ids"].append("f" * 32), "ai_finding->evidence"),
        (lambda c: c.analyses[0]["result"]["findings"][0]["evidence_refs"].__setitem__(0, "EV-099"), "ai_finding->evidence"),
        (lambda c: c.issues[0].update(correlation_group_id="CG-009"), "issue->correlation_group"),
        (lambda c: c.issues[0].update(group_key="other"), "issue->correlation_group"),
        (lambda c: c.issues[0].update(ai_finding_ids=["AI-F-404"]), "issue->ai_finding"),
        (lambda c: c.recommendations[0].update(issue_id="ISSUE-404"), "recommendation->issue"),
        (lambda c: c.recommendations[0].update(ai_analysis_id="b" * 32), "recommendation->ai_analysis"),
        (lambda c: c.recommendations[0]["evidence_ids"].append("f" * 32), "recommendation->evidence"),
        (lambda c: c.recommendations[0]["retest"].update(match_key="forged"), "recommendation->retest_spec"),
        (lambda c: c.retests[1].update(recommendation_ref=str(ObjectId())), "retest->recommendation"),
        (lambda c: c.retests[1].update(issue_id="ISSUE-404"), "retest->issue"),
        (lambda c: c.retests[1]["matched_evidence_ids"].append("f" * 32), "retest->original_evidence"),
        (lambda c: c.retests[1].update(source_run_ids=[str(ObjectId())]), "retest->source_run"),
        (lambda c: c.evidence[0].update(source_run_id=str(ObjectId())), "evidence->source_run"),
        (lambda c: c.evidence[0].update(source_finding_id="tests[7]"), "evidence->source_finding"),
        (lambda c: c.evidence[2].update(source_finding_id="f-404"), "evidence->source_finding"),
        (lambda c: setattr(c, "qa_run", None), "assessment->qa_run"),
        (lambda c: c.security_run.update(target_id=str(ObjectId())), "assessment->security_run"),
    ],
)
def test_broken_references_are_reported_not_repaired(mutate, relationship) -> None:
    inputs = chain()
    mutate(inputs)
    before = copy.deepcopy(inputs)
    assert relationship in problems(inputs)
    assert inputs == before  # the audit reports; it never edits (repairs) the data


def test_cross_assessment_evidence_is_named_as_such() -> None:
    inputs = chain()
    inputs.issues[0]["evidence_ids"].append("f" * 32)
    inputs.foreign_evidence = {"f" * 32: str(ObjectId())}
    errors = [e for e in audit(inputs).errors if e.relationship == "issue->evidence"]
    assert any(e.problem == "evidence belongs to a different assessment" for e in errors)


def test_error_messages_carry_references_not_content() -> None:
    inputs = chain()
    inputs.evidence[0]["actual"] = "password=hunter22"
    inputs.evidence[0]["source_finding_id"] = "tests[9]"
    text = str([e.as_dict() for e in audit(inputs).errors])
    assert "hunter22" not in text and "EV-001" in text


# --- assembly --------------------------------------------------------------------------------


def test_summary_uses_stored_values_and_keeps_concepts_apart() -> None:
    model = build(chain())
    s = model["summary"]
    assert s["qa"]["failed"] == 1 and s["security"]["medium"] == 1 and s["evidence_total"] == 3
    assert s["priority_counts"] == {"P1": 0, "P2": 1, "P3": 0, "P4": 0}
    assert s["retests"] == {"total": 3, "passed": 1, "failed": 1, "execution_failed": 1, "running": 0}
    issue = model["correlation"]["issues"][0]
    assert (issue["priority"], issue["priority_score"], issue["tool_severity"], issue["ai_confidence"]) == ("P2", 55, "medium", "high")
    assert [f["points"] for f in issue["score_factors"]] == [50, 5]
    assert model["meta"]["report_version"] == REPORT_VERSION


def test_execution_failure_never_becomes_fail() -> None:
    rows = {r["retest_id"]: r for r in build(chain())["retests"]}
    assert (rows["RETEST-001"]["outcome"], rows["RETEST-001"]["verdict"]) == ("EXECUTION_FAILED", None)
    assert rows["RETEST-002"]["outcome"] == "FAIL" and rows["RETEST-002"]["matched_evidence_refs"] == ["EV-003"]
    assert rows["RETEST-003"]["outcome"] == "PASS"
    assert retest_outcome({"status": "failed", "verdict": "FAIL"}) == "EXECUTION_FAILED"
    assert retest_outcome({"status": "running"}) == "RUNNING"


def test_partial_and_minimal_assessments_are_reported_honestly() -> None:
    inputs = chain()
    inputs.assessment.update(partial=True, security_status="failed", security_error="ZAP not reachable",
                             ai_analysis_status="not_analyzed", correlation=None, recommendation=None)
    inputs.analyses, inputs.groups, inputs.issues, inputs.recommendations, inputs.retests = [], [], [], [], []
    model = build(inputs)
    assert model["summary"]["partial"] is True
    assert model["ai"]["analysis"] is None and model["summary"]["recommendation_status"] == "not_generated"
    assert model["summary"]["correlation_status"] == "not_run" and model["retests"] == []
    html = render_html(model)
    assert "PARTIAL ASSESSMENT" in html and "ZAP not reachable" in html
    assert "No completed AI analysis exists" in html and "No retests have been run." in html


def test_failed_ai_attempt_is_reported_not_hidden() -> None:
    inputs = chain()
    inputs.analyses.append({"_id": ObjectId(), "analysis_id": "c" * 32, "assessment_id": str(inputs.assessment["_id"]),
                            "status": "failed", "provider": "openai", "model": "m", "created_at": datetime(2026, 9, 23, tzinfo=timezone.utc),
                            "error": {"category": "authentication", "message": "401 invalid_api_key"}})
    model = build(inputs)
    assert model["ai"]["failed_attempts"] == 1 and model["ai"]["latest_failure"]["category"] == "authentication"
    assert model["ai"]["analysis"]["analysis_id"] == "a" * 32  # the completed one is still the one shown


def test_registry_changes_do_not_replace_the_snapshot() -> None:
    inputs = chain()
    inputs.target["base_url"] = "http://renamed.invalid"
    target = build(inputs)["target"]
    assert target["base_url"] == "http://t.invalid" and target["registry_differs"] is True


def test_fingerprint_ignores_generation_metadata_only() -> None:
    a, b = build(chain_fixed := chain()), None
    b = copy.deepcopy(a)
    b["meta"].update(report_id="REPORT-009", generated_at="2030-01-01T00:00:00Z")
    assert fingerprint(a) == fingerprint(b)
    b["summary"]["issue_total"] = 99
    assert fingerprint(a) != fingerprint(b)
    assert chain_fixed is not None


# --- rendering ----------------------------------------------------------------------------------


def test_html_is_self_contained_with_every_section_and_reference() -> None:
    html = render_html(build(chain()))
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    for sid, title in SECTIONS:
        assert f'id="{sid}"' in html and title in html
    for ref in ("EV-001", "EV-002", "EV-003", "ISSUE-001", "CG-001", "REC-001", "RETEST-001", "RETEST-002", "RETEST-003"):
        assert ref in html
    assert "ADVISORY ONLY" in html and "no automatic source-code modification occurred" in html
    assert "Execution failed - the engine could not execute. No PASS/FAIL verdict." in html
    assert not re.search(r"<script|<link|src=|https?://(?!t\.invalid)", html, re.I)
    assert not re.search(r">\s*(Apply|Auto[- ]?fix|Execute)\b", html)


def test_html_escapes_stored_text() -> None:
    inputs = chain()
    inputs.evidence[0]["actual"] = '<img src=x onerror="alert(1)">'
    html = render_html(build(inputs))
    assert "<img src=x" not in html and "&lt;img src=x" in html


def test_rendering_is_deterministic() -> None:
    model = build(chain())
    assert render_html(model) == render_html(copy.deepcopy(model))
    assert render_pdf(model) == render_pdf(copy.deepcopy(model))


def test_pdf_is_valid_and_carries_the_report_content() -> None:
    pdf = render_pdf(build(chain()))
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF") and len(pdf) > 3000
    for text in (b"Executive summary", b"Target information", b"Assessment pipeline", b"QA results", b"Security results",
                 b"Evidence", b"AI analysis", b"Correlation and prioritized issues", b"Recommendations", b"Retests",
                 b"Traceability audit", b"ADVISORY ONLY", b"EV-003", b"ISSUE-001", b"REC-001", b"RETEST-002", b"REPORT-001"):
        assert text in pdf, text


# --- secrets --------------------------------------------------------------------------------------


SECRETS = {
    "openai": "sk-proj-" + "A" * 40,
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlc2ln",
    "bearer": "Authorization: Bearer abcdefghijklmnop123",
    "cookie": "Cookie: session=verysecretsessionvalue",
    "password": "password=Sup3rS3cret!",
    "url": "mongodb://admin:hunter2@db.internal:27017",
}


def test_secrets_in_stored_text_never_reach_html_or_pdf() -> None:
    inputs = chain()
    inputs.evidence[0]["actual"] = " | ".join(SECRETS.values())
    inputs.analyses[0]["result"]["overall_assessment"] = SECRETS["openai"] + " " + SECRETS["jwt"]
    inputs.recommendations[0]["description"] = SECRETS["bearer"] + " " + SECRETS["password"]
    model = build(inputs)
    html, pdf = render_html(model), render_pdf(model).decode("latin-1")
    for text in (html, pdf):
        assert find_leaks(text) == []
        for needle in ("A" * 40, "c2lnbmF0dXJlc2ln", "abcdefghijklmnop123", "verysecretsessionvalue", "Sup3rS3cret", "hunter2"):
            assert needle not in text
    assert "should-not-appear" not in html  # evidence_payload is never rendered


def test_leak_detector_finds_unredacted_secrets_and_configured_values() -> None:
    for value in SECRETS.values():
        assert find_leaks(value), value
    assert find_leaks("password: [REDACTED] Bearer [REDACTED]") == []

    class S:
        openai_api_key, zap_api_key, mongodb_uri = "k" * 20, "zapkey123", "mongodb://u:p4ssw0rd@h/db"
    secrets = known_secrets(S())
    assert "zapkey123" in secrets and find_leaks("x zapkey123 y", secrets) == ["configured_secret"]


# --- guardrails ------------------------------------------------------------------------------------


REPORT_FILES = [*sorted((APP / "engines" / "reporting").glob("*.py")), APP / "services" / "report_service.py",
                APP / "api" / "routes" / "reports.py", APP / "models" / "report.py", APP / "schemas" / "report.py"]
FORBIDDEN_IMPORTS = ("openai", "playwright", "subprocess", "shutil", "socket", "httpx", "requests", "urllib", "docker",
                     "redis", "celery", "app.engines.qa", "app.engines.security", "app.engines.orchestrator.orchestrator",
                     "app.engines.ai.openai_provider", "app.engines.ai.provider", "app.engines.correlation",
                     "app.engines.remediation", "app.engines.retest", "app.services.qa_service", "app.services.security_service",
                     "app.services.ai_analysis_service", "app.services.correlation_service",
                     "app.services.recommendation_service", "app.services.retest_service")


@pytest.mark.parametrize("path", REPORT_FILES, ids=lambda p: p.name)
def test_report_layer_imports_nothing_that_runs_or_reruns(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    for name in names:
        assert not any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS), (path.name, name)
    calls = {n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not calls & {"eval", "exec", "Popen", "system", "unlink", "rmtree", "delete_one", "delete_many", "drop"}


def test_report_service_writes_only_reports() -> None:
    source = (APP / "services" / "report_service.py").read_text(encoding="utf-8")
    writes = re.findall(r"self\._(\w+)\.(insert_one|insert_many|update_one|update_many|replace_one|find_one_and_update)", source)
    assert writes and {collection for collection, _ in writes} == {"reports"}


def test_final_verification_script_is_read_only() -> None:
    source = (APP.parent / "scripts" / "final_verification.py").read_text(encoding="utf-8")
    assert not re.search(r"\.(insert_\w+|update_\w+|replace_one|delete_\w+|drop\w*|find_one_and_\w+|write_\w+|unlink|rmdir)\(", source)
    assert "generate(" not in source and "execute(" not in source  # never produces the evidence it looks for


def test_pdf_library_is_confined_to_the_pdf_renderer() -> None:
    users = [p.relative_to(APP).as_posix() for p in APP.rglob("*.py") if re.search(r"^\s*(from|import) reportlab", p.read_text(encoding="utf-8"), re.M)]
    assert users == ["engines/reporting/pdf_renderer.py"]
