"""Phase 9 unit tests: retest plan, verdict, schemas and guardrails.

Pure functions over hand-made records - no database, no engine, no model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.engines.correlation.keys import correlation_key
from app.engines.remediation.models import RetestSpecification
from app.engines.retest.plan import RetestNotEligibleError, plan_retest
from app.engines.retest.verdict import evaluate, execution_problem
from app.schemas.retest import RetestRequest, RetestResponse

CSP_EVIDENCE = {
    "finding_type": "security",
    "source": "zap",
    "category": "passive_scan",
    "title": "CSP Header Not Set",
    "target_component": "GET http://app.test/",
    "status": "failed",
    "tool_severity": "medium",
    "evidence_payload": {"rule_id": "10038"},
}
CSP_KEY = correlation_key(CSP_EVIDENCE).group_key


def check(**kw: Any) -> dict[str, Any]:
    base = {
        "evidence_id": "e1",
        "evidence_ref": "EV-002",
        "source": "zap",
        "finding_type": "security",
        "rule_id": "10038",
        "title": "CSP Header Not Set",
        "target_component": "GET http://app.test/",
        "baseline_status": "failed",
    }
    base.update(kw)
    return base


def spec(**kw: Any) -> RetestSpecification:
    base = {
        "retest_type": "security_rescan",
        "scope": "origin",
        "target_id": "t1",
        "target_component": "http://app.test",
        "issue_id": "ISSUE-002",
        "match_key": CSP_KEY,
        "correlation_rule": "same_missing_header_and_origin",
        "pass_condition": "finding_absent",
        "checks": [check()],
        "preconditions": [],
        "expected_result": "x",
        "pass_criteria": "x",
        "fail_criteria": "x",
    }
    base.update(kw)
    return RetestSpecification.model_validate(base)


QA_CHECK = check(evidence_id="e0", evidence_ref="EV-001", source="playwright", finding_type="qa",
                 rule_id=None, title="Page Title", target_component="http://app.test/")


def qa_spec(**kw: Any) -> RetestSpecification:
    base: dict[str, Any] = dict(
        retest_type="qa_recheck", scope="component", target_component="http://app.test/",
        match_key="qa|same_qa_check_and_component|functional:page title|http://app.test",
        correlation_rule="same_qa_check_and_component", pass_condition="check_passes",
        checks=[QA_CHECK],
    )
    base.update(kw)
    return spec(**base)


# --- specification and schema ----------------------------------------------------


@pytest.mark.parametrize("retest_type", ["full_scan", "auto_fix", "", None])
def test_unsupported_retest_types_are_rejected(retest_type) -> None:
    with pytest.raises(ValidationError):
        spec(retest_type=retest_type)


@pytest.mark.parametrize("field", ["match_key", "pass_condition", "checks", "target_id"])
def test_required_specification_fields(field) -> None:
    data = spec().model_dump()
    data.pop(field)
    with pytest.raises(ValidationError):
        RetestSpecification.model_validate(data)


def test_request_body_accepts_nothing() -> None:
    RetestRequest.model_validate({})
    with pytest.raises(ValidationError):
        RetestRequest.model_validate({"retest_type": "security_rescan"})


def test_response_status_and_verdict_vocabularies() -> None:
    assert set(RetestResponse.model_fields["status"].annotation.__args__) == {"running", "completed", "failed"}
    names = set(RetestResponse.model_fields)
    for banned in ("fixed", "remediated", "applied", "resolved", "closed"):
        assert not any(banned in name for name in names)


# --- plan: only the specified scope ---------------------------------------------------


def test_security_rescan_runs_only_the_checks_scanners() -> None:
    assert plan_retest(spec(), {}).components == frozenset({"zap"})
    probe = check(source="api_probe", rule_id="api-probe-disclosure-x-powered-by")
    assert plan_retest(spec(checks=[probe]), {}).components == frozenset({"api_probes"})
    both = plan_retest(spec(checks=[check(), probe]), {})
    assert both.engine == "security" and both.components == frozenset({"zap", "api_probes"})


def test_qa_recheck_runs_only_the_named_check() -> None:
    plan = plan_retest(qa_spec(), {"e0": "functional"})
    assert plan.engine == "qa" and plan.qa_checks == ("Page Title",)
    console = check(evidence_id="e5", source="playwright", finding_type="qa", rule_id=None,
                    title="Browser console error", baseline_status="observed")
    plan = plan_retest(spec(retest_type="qa_recheck", checks=[console]), {"e5": "client_errors"})
    assert plan.qa_checks == ("Console Error Collection",)


@pytest.mark.parametrize(
    "bad",
    [
        lambda: spec(checks=[QA_CHECK]),  # security rescan of a QA check
        lambda: qa_spec(checks=[check()]),  # QA recheck of a scanner finding
        lambda: spec(pass_condition="check_passes"),  # security can only be finding_absent
        lambda: spec(checks=[check(source="nikto")]),  # a scanner this platform does not have
        lambda: qa_spec(checks=[check(**{**QA_CHECK, "title": "Checkout works"})]),  # not in the suite
        lambda: spec(checks=[]),
    ],
    ids=["qa-in-security", "security-in-qa", "security-check-passes", "unknown-scanner", "unknown-qa-check", "no-checks"],
)
def test_ineligible_specifications_are_never_widened(bad) -> None:
    with pytest.raises(RetestNotEligibleError):
        plan_retest(bad(), {"e0": "functional"})


# --- verdict --------------------------------------------------------------------------------


def sec_run(components: dict[str, str], error: str | None = None) -> dict[str, Any]:
    return {"id": "r1", "status": "completed", "error": error,
            "components": [{"name": n, "status": s} for n, s in components.items()]}


def test_security_finding_present_is_fail_absent_is_pass() -> None:
    plan = plan_retest(spec(), {})
    again = [{**CSP_EVIDENCE, "target_component": "GET http://app.test/other", "source_run_id": "r1",
              "source_finding_id": "f9"}]
    fail = evaluate(spec(), plan, again)
    assert fail.verdict == "FAIL" and fail.observations[0]["correlation_key"] == CSP_KEY
    unrelated = [{**CSP_EVIDENCE, "title": "Something else", "evidence_payload": {"rule_id": "10099"}}]
    assert evaluate(spec(), plan, unrelated).verdict == "PASS"
    assert evaluate(spec(), plan, []).verdict == "PASS"
    # Informational/passed results do not count, exactly as in Phase 6 correlation.
    assert evaluate(spec(), plan, [{**CSP_EVIDENCE, "status": "passed"}]).verdict == "PASS"


def test_qa_check_passes_or_fails() -> None:
    plan = plan_retest(qa_spec(), {"e0": "functional"})
    passed = {"finding_type": "qa", "source": "playwright", "title": "Page Title", "category": "functional",
              "target_component": "http://app.test/", "status": "passed"}
    assert evaluate(qa_spec(), plan, [passed]).verdict == "PASS"
    assert evaluate(qa_spec(), plan, [{**passed, "status": "failed"}]).verdict == "FAIL"
    assert evaluate(qa_spec(), plan, [{**passed, "status": "error"}]).verdict == "FAIL"


def test_execution_problems_are_not_verdicts() -> None:
    plan = plan_retest(spec(), {})
    assert execution_problem(plan, sec_run({"zap": "completed", "api_probes": "skipped"})) is None
    assert "did not complete" in execution_problem(plan, sec_run({"zap": "failed"}))
    assert "did not complete" in execution_problem(plan, sec_run({"zap": "skipped"}))
    assert execution_problem(plan, sec_run({"api_probes": "completed"})) is not None
    assert execution_problem(plan, sec_run({"zap": "completed"}, error="boom")) is not None

    qa_plan = plan_retest(qa_spec(), {"e0": "functional"})
    ok = {"status": "passed", "tests": [{"name": "Application Reachability"}, {"name": "Page Title"}]}
    assert execution_problem(qa_plan, ok) is None
    assert execution_problem(qa_plan, {"status": "error", "error": "no browser", "tests": []}) is not None
    assert execution_problem(qa_plan, {"status": "passed", "tests": [{"name": "Application Reachability"}]}) is not None


# --- guardrails ------------------------------------------------------------------------------

APP = Path(__file__).resolve().parents[1] / "app"
PHASE9_FILES = [
    *sorted((APP / "engines" / "retest").glob("*.py")),
    APP / "services" / "retest_service.py",
    APP / "api" / "routes" / "retests.py",
    APP / "models" / "retest.py",
    APP / "schemas" / "retest.py",
]


@pytest.mark.parametrize("path", PHASE9_FILES, ids=lambda p: p.name)
def test_retest_layer_runs_only_existing_engines_through_services(path: Path) -> None:
    source = path.read_text(encoding="utf-8-sig")
    imports = "\n".join(re.findall(r"^\s*(?:from|import)\s+[\w.]+", source, re.MULTILINE))
    for banned in ("openai", "app.engines.ai", "app.services.ai_analysis_service",
                   "app.services.recommendation_service", "subprocess", "shutil", "pathlib", "os",
                   "httpx", "requests", "urllib", "socket", "docker", "redis", "celery",
                   "app.engines.qa.playwright_runner", "app.engines.security"):
        assert not re.search(rf"(from|import)\s+{re.escape(banned)}(\s|\.|$)", imports), f"{path.name} imports {banned}"
    for call in ("eval(", "exec(", "os.system(", "__import__(", " open(", "Popen", ".write_text(",
                 ".unlink(", "shell=True"):
        assert call not in source, f"{path.name} uses {call}"


def test_retest_service_writes_only_retests() -> None:
    source = (APP / "services" / "retest_service.py").read_text(encoding="utf-8")
    writers = set(re.findall(
        r"self\._(\w+)\.(?:update_one|update_many|delete_one|delete_many|insert_one|insert_many|replace_one)", source))
    assert writers == {"retests"}
    assert "delete_" not in source  # history is never deleted
