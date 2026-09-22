"""Orchestrator unit tests: state machine, normalization and sequencing.

No MongoDB, no browser, no ZAP. The orchestrator is driven through its
ports with in-memory fakes, which is exactly what the ports are for. The
real services and the real database are exercised in
``test_assessments_api.py``.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.engines.orchestrator.models import (
    AssessmentState,
    EvidenceStatus,
    EvidenceType,
    StageStatus,
)
from app.engines.orchestrator.normalizer import (
    QA_CHECKS,
    normalize_assessment,
    normalize_qa_run,
    normalize_security_run,
    security_category,
    security_coverage,
    summarise,
)
from app.engines.orchestrator.orchestrator import (
    AssessmentOrchestrationError,
    AssessmentOrchestrator,
    AssessmentPersistenceError,
    TargetNotAssessableError,
)
from app.engines.orchestrator.state_machine import (
    ALLOWED_TRANSITIONS,
    AssessmentStateMachine,
    IllegalStateTransition,
)
from app.services.target_service import TargetNotFoundError

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
HAPPY_PATH = ["created", "running", "qa_running", "security_running", "normalizing", "completed"]


# --- fixtures: raw runs shaped exactly like the stored documents ----------


def qa_run(**overrides: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": "qa0000000000000000000001",
        "target_base_url": "http://target.invalid",
        "status": "failed",
        "started_at": T0,
        "finished_at": T0 + timedelta(seconds=2),
        "error": None,
        "tests": [
            {
                "name": "Application Reachability",
                "status": "passed",
                "duration_ms": 30,
                "url": "http://target.invalid/",
                "title": "Shop",
                "error": None,
                "details": {"http_status": 200, "ok": True},
            },
            {
                "name": "Page Title",
                "status": "failed",
                "duration_ms": 4,
                "url": "http://target.invalid/",
                "title": "",
                "error": "Page title is missing or empty",
                "details": {},
            },
            {
                "name": "DOM Availability",
                "status": "passed",
                "duration_ms": 6,
                "url": "http://target.invalid/",
                "title": "Shop",
                "error": None,
                "details": {"html_length": 1200, "element_count": 40, "body_text_length": 9},
            },
        ],
        "console_errors": [
            {"type": "error", "message": "Failed to load resource", "location": "app.js:1"}
        ],
        "network_failures": [
            {"url": "http://target.invalid/api/x", "method": "GET", "status": 500, "failure": None}
        ],
    }
    run.update(overrides)
    return run


def security_run(**overrides: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": "se0000000000000000000001",
        "target_base_url": "http://target.invalid",
        "status": "completed",
        "started_at": T0 + timedelta(seconds=3),
        "finished_at": T0 + timedelta(seconds=9),
        "error": None,
        "components": [
            {"name": "zap", "status": "completed", "detail": None},
            {"name": "api_probes", "status": "completed", "detail": None},
            {"name": "semgrep", "status": "skipped", "detail": "no source_path"},
        ],
        "findings": [
            {
                "id": "f-high",
                "source": "api_probe",
                "rule_id": "api-probe-cors-reflect-credentials",
                "name": "CORS reflects arbitrary origin with credentials",
                "severity": "high",
                "url": "http://target.invalid:9998",
                "method": "OPTIONS",
                "evidence": "access-control-allow-origin: https://probe.invalid",
                "description": "long text " * 50,
                "raw": {"big": "x" * 1000},
            },
            {
                "id": "f-zap",
                "source": "zap",
                "rule_id": "10038",
                "name": "Content Security Policy (CSP) Header Not Set",
                "severity": "medium",
                "confidence": "high",
                "url": "http://target.invalid/",
                "method": "GET",
                "evidence": "",
                "cwe": "693",
                "wasc": "15",
                "solution": "long text " * 50,
            },
            {
                "id": "f-probe",
                "source": "api_probe",
                "rule_id": "api-probe-disclosure-x-powered-by",
                "name": "Technology disclosed in X-Powered-By",
                "severity": "low",
                "url": "http://target.invalid:9998",
                "method": "GET",
                "evidence": "x-powered-by: Express",
            },
            {
                "id": "f-semgrep",
                "source": "semgrep",
                "rule_id": "python.lang.security.eval",
                "name": "eval",
                "severity": "informational",
                "url": "src/app.py:12",
                "evidence": "eval(user_input)",
            },
        ],
    }
    run.update(overrides)
    return run


# --- state machine ---------------------------------------------------------


def test_happy_path_transitions_are_legal() -> None:
    machine = AssessmentStateMachine()
    for state in HAPPY_PATH[1:]:
        machine.transition_to(AssessmentState(state), f"to {state}")
    assert [t.state.value for t in machine.history] == HAPPY_PATH
    assert machine.is_final


@pytest.mark.parametrize(
    ("path", "illegal"),
    [
        ([], "security_running"),
        ([], "qa_running"),
        ([], "completed"),
        (["running"], "normalizing"),
        (["running", "qa_running"], "completed"),
        (["running", "qa_running"], "normalizing"),
        (["running", "qa_running", "security_running"], "completed"),
    ],
)
def test_skipping_a_state_is_illegal(path: list[str], illegal: str) -> None:
    machine = AssessmentStateMachine()
    for state in path:
        machine.transition_to(AssessmentState(state))
    with pytest.raises(IllegalStateTransition):
        machine.transition_to(AssessmentState(illegal))
    # A refused move changes nothing.
    assert machine.state.value == (path[-1] if path else "created")


@pytest.mark.parametrize("depth", range(len(HAPPY_PATH) - 1))
def test_every_active_state_can_fail(depth: int) -> None:
    machine = AssessmentStateMachine()
    for state in HAPPY_PATH[1 : depth + 1]:
        machine.transition_to(AssessmentState(state))
    transition = machine.fail("engine exploded")
    assert transition is not None
    assert machine.state is AssessmentState.FAILED
    assert machine.history[-1].message == "engine exploded"


def test_final_states_are_terminal() -> None:
    machine = AssessmentStateMachine()
    for state in HAPPY_PATH[1:]:
        machine.transition_to(AssessmentState(state))
    with pytest.raises(IllegalStateTransition):
        machine.transition_to(AssessmentState.FAILED)
    assert machine.fail("too late") is None
    assert machine.state is AssessmentState.COMPLETED


def test_analyzing_is_entered_only_from_completed_and_returns_to_it() -> None:
    """Phase 5: AI analysis is attached to a finished assessment only."""
    reachable_from = {
        state for state, allowed in ALLOWED_TRANSITIONS.items()
        if AssessmentState.ANALYZING in allowed
    }
    assert reachable_from == {AssessmentState.COMPLETED}
    assert ALLOWED_TRANSITIONS[AssessmentState.ANALYZING] == {AssessmentState.COMPLETED}

    # The pipeline itself can never wander into it.
    machine = AssessmentStateMachine()
    for state in HAPPY_PATH[1:-1]:
        machine.transition_to(AssessmentState(state))
    with pytest.raises(IllegalStateTransition):
        machine.transition_to(AssessmentState.ANALYZING)

    # AI trouble can never fail a completed assessment.
    assert AssessmentState.FAILED not in ALLOWED_TRANSITIONS[AssessmentState.ANALYZING]


def test_history_is_ordered_timestamped_and_described() -> None:
    machine = AssessmentStateMachine(message="Assessment created")
    machine.transition_to(AssessmentState.RUNNING, "Pipeline started")
    documents = machine.history_documents()

    assert [d["state"] for d in documents] == ["created", "running"]
    assert [d["message"] for d in documents] == ["Assessment created", "Pipeline started"]
    assert all(d["timestamp"].tzinfo is not None for d in documents)
    assert documents[0]["timestamp"] <= documents[1]["timestamp"]


# --- normalization: QA -----------------------------------------------------


def test_expectation_table_matches_the_generic_smoke_suite() -> None:
    """If the suite gains or renames a check, this table must follow."""
    from app.engines.qa.smoke_suite import SMOKE_SUITE

    assert set(QA_CHECKS) == {name for name, _ in SMOKE_SUITE}


def test_playwright_result_is_normalized_with_its_real_expectation() -> None:
    evidence = normalize_qa_run(qa_run())
    reachability = evidence[0]

    assert reachability.source == "playwright"
    assert reachability.finding_type is EvidenceType.QA
    assert reachability.title == "Application Reachability"
    assert reachability.category == "availability"
    assert reachability.status is EvidenceStatus.PASSED
    assert reachability.expected == "HTTP status below 400"
    assert reachability.actual == "HTTP 200"
    assert reachability.tool_severity is None
    assert reachability.source_run_id == "qa0000000000000000000001"
    assert reachability.source_finding_id == "tests[0]"
    assert reachability.timestamp == T0 + timedelta(seconds=2)


def test_a_failed_check_records_what_actually_happened() -> None:
    title = normalize_qa_run(qa_run())[1]
    assert title.status is EvidenceStatus.FAILED
    assert title.expected == "a non-empty page title"
    assert title.actual == "Page title is missing or empty"
    assert title.source_finding_id == "tests[1]"


def test_dom_check_actual_is_read_from_its_details() -> None:
    dom = normalize_qa_run(qa_run())[2]
    assert dom.actual == "1200 characters of markup, 40 elements"


def test_skipped_test_stays_skipped() -> None:
    run = qa_run(
        tests=[{"name": "Page Title", "status": "skipped", "details": {}, "error": None}],
        console_errors=[],
        network_failures=[],
    )
    (item,) = normalize_qa_run(run)
    assert item.status is EvidenceStatus.SKIPPED


def test_errored_check_is_an_engine_fact_not_a_target_failure() -> None:
    run = qa_run(
        tests=[{"name": "DOM Availability", "status": "error", "error": "Target closed"}],
        console_errors=[],
        network_failures=[],
    )
    (item,) = normalize_qa_run(run)
    assert item.status is EvidenceStatus.ERROR
    assert item.actual == "Target closed"


def test_unknown_check_gets_no_invented_expectation() -> None:
    run = qa_run(
        tests=[{"name": "Checkout Flow", "status": "passed", "details": {"steps": 4}}],
        console_errors=[],
        network_failures=[],
    )
    (item,) = normalize_qa_run(run)
    assert item.expected is None
    assert item.actual is None
    assert item.category == "functional"


def test_console_and_network_output_are_observations() -> None:
    evidence = normalize_qa_run(qa_run())
    console, network = evidence[3], evidence[4]

    assert console.status is EvidenceStatus.OBSERVED
    assert console.category == "client_errors"
    assert console.source_finding_id == "console_errors[0]"
    assert console.expected is None

    assert network.status is EvidenceStatus.OBSERVED
    assert network.target_component == "GET http://target.invalid/api/x"
    assert network.actual == "HTTP 500"
    assert network.source_finding_id == "network_failures[0]"


# --- normalization: security -----------------------------------------------


def _by_id(evidence, finding_id):
    return next(item for item in evidence if item.source_finding_id == finding_id)


def test_zap_finding_is_normalized_without_interpretation() -> None:
    item = _by_id(normalize_security_run(security_run()), "f-zap")

    assert item.source == "zap"
    assert item.finding_type is EvidenceType.SECURITY
    assert item.category == "passive_scan"
    assert item.title == "Content Security Policy (CSP) Header Not Set"
    assert item.target_component == "GET http://target.invalid/"
    assert item.status is EvidenceStatus.FAILED
    assert item.expected is None
    assert item.actual is None  # ZAP matched no evidence string; none is made up
    assert item.tool_severity == "medium"
    assert item.source_run_id == "se0000000000000000000001"


def test_api_probe_findings_keep_their_own_source_and_family() -> None:
    evidence = normalize_security_run(security_run())
    disclosure = _by_id(evidence, "f-probe")
    cors = _by_id(evidence, "f-high")

    assert disclosure.source == "api_probe"
    assert disclosure.category == "information_disclosure"
    assert disclosure.actual == "x-powered-by: Express"
    assert cors.category == "cors"
    assert security_category("api_probe", "api-probe-missing-x-frame-options") == "security_headers"
    assert security_category("api_probe", "api-probe-missing-hsts") == "transport_security"


def test_semgrep_finding_is_normalized() -> None:
    item = _by_id(normalize_security_run(security_run()), "f-semgrep")
    assert item.source == "semgrep"
    assert item.category == "static_analysis"
    assert item.target_component == "src/app.py:12"
    assert item.actual == "eval(user_input)"


def test_scanner_rated_informational_output_is_observed_not_failed() -> None:
    evidence = normalize_security_run(security_run())
    info = _by_id(evidence, "f-semgrep")
    assert info.tool_severity == "informational"
    assert info.status is EvidenceStatus.OBSERVED
    for finding_id in ("f-high", "f-zap", "f-probe"):
        assert _by_id(evidence, finding_id).status is EvidenceStatus.FAILED


def test_sources_are_never_merged() -> None:
    sources = {item.source for item in normalize_security_run(security_run())}
    assert sources == {"zap", "api_probe", "semgrep"}


def test_security_expected_is_never_fabricated() -> None:
    assert all(item.expected is None for item in normalize_security_run(security_run()))


def test_severity_is_carried_through_verbatim_and_never_invented() -> None:
    run = security_run()
    evidence = normalize_security_run(run)
    for finding in run["findings"]:
        assert _by_id(evidence, finding["id"]).tool_severity == finding["severity"]
    assert "critical" not in {item.tool_severity for item in evidence}
    assert all(item.tool_severity is None for item in normalize_qa_run(qa_run()))


def test_security_payload_is_compact() -> None:
    evidence = normalize_security_run(security_run())
    for item in evidence:
        assert "description" not in item.evidence_payload
        assert "solution" not in item.evidence_payload
        assert "raw" not in item.evidence_payload
    assert _by_id(evidence, "f-zap").evidence_payload["cwe"] == "693"


# --- normalization: assembly + summary -------------------------------------


def test_every_record_is_traceable_to_assessment_run_and_finding() -> None:
    evidence = normalize_assessment("a" * 24, qa_run(), security_run())

    assert [item.sequence for item in evidence] == list(range(len(evidence)))
    for item in evidence:
        assert item.assessment_id == "a" * 24
        assert item.source_run_id in {"qa0000000000000000000001", "se0000000000000000000001"}
        assert item.source_finding_id, item
    # QA first, then security in the run's stored order.
    assert [i.finding_type for i in evidence[:5]] == [EvidenceType.QA] * 5
    assert evidence[5].source_finding_id == "f-high"


def test_a_missing_run_contributes_no_evidence() -> None:
    only_security = normalize_assessment("a" * 24, None, security_run())
    assert {item.finding_type for item in only_security} == {EvidenceType.SECURITY}
    assert normalize_assessment("a" * 24, None, None) == []


def test_summary_is_deterministic_from_the_raw_runs() -> None:
    summary = summarise(qa_run(), security_run(), evidence_total=9)

    assert summary["qa"] == {"total": 3, "passed": 2, "failed": 1, "skipped": 0, "error": 0}
    assert summary["security"] == {
        "total": 4, "high": 1, "medium": 1, "low": 1, "informational": 1,
    }
    assert summary["total_findings"] == 1 + 4
    assert summary["evidence_total"] == 9
    assert summarise(None, None, 0)["total_findings"] == 0


def test_security_coverage_lists_every_scanner() -> None:
    coverage = security_coverage(security_run())
    assert coverage == [
        {"source": "zap", "status": "completed", "detail": None},
        {"source": "api_probes", "status": "completed", "detail": None},
        {"source": "semgrep", "status": "skipped", "detail": "no source_path"},
    ]
    assert security_coverage(None) == []


# --- orchestrator fakes ----------------------------------------------------

TARGET_ID = "t" * 24


def target(**overrides: Any) -> dict[str, Any]:
    body = {
        "id": TARGET_ID,
        "name": "Some Registered App",
        "base_url": "http://target.invalid",
        "api_url": "http://target.invalid:9998",
        "type": "web_and_api",
        "enabled": True,
    }
    body.update(overrides)
    return body


class FakeTargets:
    def __init__(self, *targets: dict[str, Any]) -> None:
        self.targets = {item["id"]: item for item in targets}

    async def get(self, target_id: str) -> dict[str, Any]:
        if target_id not in self.targets:
            raise TargetNotFoundError(f"No target with id {target_id}.")
        return dict(self.targets[target_id])


class FakeStage:
    def __init__(self, name: str, calls: list[str], run=None, exc: Exception | None = None):
        self.name, self.calls, self.result, self.exc = name, calls, run, exc

    async def run(self, target_id: str) -> dict[str, Any]:
        self.calls.append(self.name)
        if self.exc is not None:
            raise self.exc
        return dict(self.result)


class FakeStore:
    """In-memory store that records the status at every persisted update."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.evidence: list[dict[str, Any]] = []
        self.persisted_states: list[str] = []
        self.fail_on = fail_on or set()
        self._ids = (f"{n:024d}" for n in itertools.count(1))

    def _maybe_fail(self, operation: str) -> None:
        if operation in self.fail_on:
            raise AssessmentPersistenceError(f"simulated {operation} failure")

    async def create(self, document: dict[str, Any]) -> str:
        self._maybe_fail("create")
        assessment_id = next(self._ids)
        self.documents[assessment_id] = dict(document)
        self.persisted_states.append(document["status"])
        return assessment_id

    async def update(self, assessment_id, fields, transition=None) -> None:
        self._maybe_fail("update")
        document = self.documents[assessment_id]
        document.update(fields)
        if transition is not None:
            document["state_history"] = [*document["state_history"], transition]
            self.persisted_states.append(fields.get("status", document["status"]))

    async def insert_evidence(self, documents) -> None:
        self._maybe_fail("insert_evidence")
        self.evidence.extend(documents)

    async def get(self, assessment_id: str) -> dict[str, Any]:
        return {"id": assessment_id, **self.documents[assessment_id]}


def orchestrator(*, qa=None, security=None, store=None, targets=None, calls=None):
    calls = calls if calls is not None else []
    return (
        AssessmentOrchestrator(
            targets=targets or FakeTargets(target()),
            qa=qa or FakeStage("qa", calls, run=qa_run()),
            security=security or FakeStage("security", calls, run=security_run()),
            store=store or FakeStore(),
        ),
        calls,
    )


# --- orchestrator: sequencing ------------------------------------------------


async def test_qa_runs_before_security() -> None:
    calls: list[str] = []
    runner, _ = orchestrator(calls=calls)
    await runner.run(TARGET_ID)
    assert calls == ["qa", "security"]


async def test_every_transition_is_persisted_as_it_happens() -> None:
    store = FakeStore()
    runner, _ = orchestrator(store=store)
    result = await runner.run(TARGET_ID)

    assert store.persisted_states == HAPPY_PATH
    assert [t["state"] for t in result["state_history"]] == HAPPY_PATH
    assert all(t["message"] for t in result["state_history"])
    assert result["status"] == "completed"


async def test_both_run_ids_and_stage_outcomes_are_recorded() -> None:
    result = (await orchestrator()[0].run(TARGET_ID))

    assert result["qa_run_id"] == "qa0000000000000000000001"
    assert result["security_run_id"] == "se0000000000000000000001"
    assert result["qa_status"] == "completed"
    assert result["security_status"] == "completed"
    assert result["qa_run_status"] == "failed"
    assert result["security_run_status"] == "completed"
    assert result["partial"] is False
    assert result["started_at"] is not None and result["finished_at"] is not None
    assert result["duration_ms"] >= 0


async def test_target_is_snapshotted() -> None:
    result = await orchestrator()[0].run(TARGET_ID)
    assert result["target_name"] == "Some Registered App"
    assert result["target_base_url"] == "http://target.invalid"
    assert result["target_type"] == "web_and_api"


async def test_evidence_is_persisted_with_the_assessment_id() -> None:
    store = FakeStore()
    result = await orchestrator(store=store)[0].run(TARGET_ID)

    assert len(store.evidence) == result["evidence_count"] == 9
    assert {item["assessment_id"] for item in store.evidence} == {result["id"]}
    assert result["summary"]["evidence_total"] == 9
    assert result["summary"]["total_findings"] == 5
    assert result["security_coverage"][2]["status"] == "skipped"


async def test_findings_and_failing_tests_do_not_fail_the_assessment() -> None:
    result = await orchestrator()[0].run(TARGET_ID)
    assert result["summary"]["qa"]["failed"] == 1
    assert result["summary"]["security"]["high"] == 1
    assert result["status"] == "completed"
    assert result["error"] is None


async def test_the_orchestrator_never_enters_analyzing() -> None:
    result = await orchestrator()[0].run(TARGET_ID)
    assert "analyzing" not in [t["state"] for t in result["state_history"]]


# --- orchestrator: validation ----------------------------------------------


async def test_unknown_target_is_rejected_before_anything_is_created() -> None:
    store = FakeStore()
    runner, calls = orchestrator(store=store, targets=FakeTargets())
    with pytest.raises(TargetNotFoundError):
        await runner.run(TARGET_ID)
    assert store.documents == {} and calls == []


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"enabled": False}, "disabled"),
        ({"type": "api"}, "web target"),
        ({"base_url": "  "}, "no base_url"),
    ],
)
async def test_unassessable_target_is_rejected_before_anything_runs(
    overrides: dict[str, Any], fragment: str
) -> None:
    store = FakeStore()
    runner, calls = orchestrator(store=store, targets=FakeTargets(target(**overrides)))
    with pytest.raises(TargetNotAssessableError, match=fragment):
        await runner.run(TARGET_ID)
    assert store.documents == {} and calls == []


# --- orchestrator: partial and total failure --------------------------------


async def test_qa_execution_failure_is_recorded_and_security_still_runs() -> None:
    calls: list[str] = []
    store = FakeStore()
    runner, _ = orchestrator(
        calls=calls,
        store=store,
        qa=FakeStage("qa", calls, exc=RuntimeError("browser would not launch")),
    )
    result = await runner.run(TARGET_ID)

    assert calls == ["qa", "security"]
    assert result["status"] == "completed"
    assert result["partial"] is True
    assert result["qa_status"] == "failed"
    assert "browser would not launch" in result["qa_error"]
    assert result["qa_run_id"] is None
    assert result["security_status"] == "completed"
    # No QA run, so no QA evidence - nothing is fabricated for it.
    assert {item["finding_type"] for item in store.evidence} == {"security"}
    assert result["summary"]["qa"]["total"] == 0
    assert "partial" in result["state_history"][-1]["message"]


async def test_an_engine_that_reports_it_could_not_execute_is_a_stage_failure() -> None:
    broken = qa_run(status="error", error="Executable doesn't exist", tests=[],
                    console_errors=[], network_failures=[])
    calls: list[str] = []
    runner, _ = orchestrator(calls=calls, qa=FakeStage("qa", calls, run=broken))
    result = await runner.run(TARGET_ID)

    assert result["qa_status"] == "failed"
    # The run is real and stored, so it stays referenced for traceability.
    assert result["qa_run_id"] == broken["id"]
    assert result["qa_run_status"] == "error"
    assert result["partial"] is True
    assert result["status"] == "completed"


async def test_security_execution_failure_is_recorded() -> None:
    calls: list[str] = []
    store = FakeStore()
    runner, _ = orchestrator(
        calls=calls,
        store=store,
        security=FakeStage("security", calls, exc=ConnectionError("ZAP unreachable")),
    )
    result = await runner.run(TARGET_ID)

    assert result["status"] == "completed"
    assert result["partial"] is True
    assert result["security_status"] == "failed"
    assert "ZAP unreachable" in result["security_error"]
    assert result["security_run_id"] is None
    assert {item["finding_type"] for item in store.evidence} == {"qa"}
    assert result["security_coverage"] == []


async def test_both_stages_failing_fails_the_assessment() -> None:
    calls: list[str] = []
    store = FakeStore()
    runner, _ = orchestrator(
        calls=calls,
        store=store,
        qa=FakeStage("qa", calls, exc=RuntimeError("no browser")),
        security=FakeStage("security", calls, exc=RuntimeError("no scanner")),
    )
    result = await runner.run(TARGET_ID)

    assert result["status"] == "failed"
    assert "no browser" in result["error"] and "no scanner" in result["error"]
    states = [t["state"] for t in result["state_history"]]
    assert states == ["created", "running", "qa_running", "security_running", "failed"]
    assert store.evidence == []
    assert result["qa_status"] == result["security_status"] == "failed"


async def test_evidence_persistence_failure_fails_the_assessment_and_raises() -> None:
    store = FakeStore(fail_on={"insert_evidence"})
    runner, _ = orchestrator(store=store)
    with pytest.raises(AssessmentPersistenceError):
        await runner.run(TARGET_ID)

    (document,) = store.documents.values()
    assert document["status"] == "failed"
    assert "simulated insert_evidence failure" in document["error"]
    assert document["state_history"][-1]["state"] == "failed"


async def test_creation_failure_raises_without_running_anything() -> None:
    store = FakeStore(fail_on={"create"})
    runner, calls = orchestrator(store=store)
    with pytest.raises(AssessmentPersistenceError):
        await runner.run(TARGET_ID)
    assert calls == []


async def test_an_orchestrator_bug_is_an_orchestration_error(monkeypatch) -> None:
    import app.engines.orchestrator.orchestrator as module

    def broken(*_args, **_kwargs):
        raise KeyError("normalizer bug")

    monkeypatch.setattr(module, "normalize_assessment", broken)
    store = FakeStore()
    runner, _ = orchestrator(store=store)
    with pytest.raises(AssessmentOrchestrationError):
        await runner.run(TARGET_ID)
    (document,) = store.documents.values()
    assert document["status"] == "failed"


# --- guard rails -------------------------------------------------------------

ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1] / "app" / "engines" / "orchestrator"
ASSESSMENT_SERVICE = (
    Path(__file__).resolve().parents[1] / "app" / "services" / "assessment_service.py"
)


def test_orchestrator_contains_no_target_specific_values() -> None:
    banned = ["mini e-commerce", "mini-ecommerce", "localhost:3000", "localhost:4000", "6aa9dc1a"]
    offenders: list[str] = []
    for path in [*sorted(ORCHESTRATOR_DIR.glob("*.py")), ASSESSMENT_SERVICE]:
        source = path.read_text(encoding="utf-8").lower()
        offenders += [f"{path.name}: {n}" for n in banned if n in source]
    assert offenders == [], f"target-specific values leaked: {offenders}"


def test_orchestrator_never_touches_a_tool_a_framework_or_ai_directly() -> None:
    """It sequences services; engines, HTTP, the database and AI are out of reach."""
    banned = [
        "playwright",
        "zap_runner",
        "api_probes",
        "semgrep_runner",
        "import fastapi",
        "from fastapi",
        "pymongo",
        "openai",
        "aiprovider",
    ]
    offenders: list[str] = []
    for path in sorted(ORCHESTRATOR_DIR.glob("*.py")):
        code = "\n".join(
            line
            for line in path.read_text(encoding="utf-8").lower().splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        offenders += [f"{path.name}: {n}" for n in banned if n in code]
    assert offenders == [], f"orchestrator imports something it must not: {offenders}"


def test_state_enum_matches_the_documented_lifecycle() -> None:
    assert [s.value for s in AssessmentState] == [
        "created", "running", "qa_running", "security_running",
        "normalizing", "analyzing", "completed", "failed",
    ]
    assert {s.value for s in StageStatus} == {"pending", "running", "completed", "failed"}
