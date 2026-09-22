"""Assessment API tests against the real MongoDB.

The QA and security *services* are real here - only their engines are faked
- so the orchestration path, raw-run persistence, evidence persistence and
the HTTP contract are all genuinely exercised without Chromium or ZAP. The
last test runs the whole thing for real when the tools and a target are up.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.engines.qa.models import QaRunOutcome
from app.engines.qa.models import RunStatus as QaRunStatus
from app.engines.qa.models import TestResult, TestStatus
from app.engines.security.models import (
    ComponentResult,
    ComponentStatus,
    SecurityFinding,
    SecurityRunOutcome,
    Severity,
)
from app.engines.security.models import RunStatus as SecurityRunStatus

pytestmark = pytest.mark.integration

MISSING_ID = "0" * 24
HAPPY_PATH = ["created", "running", "qa_running", "security_running", "normalizing", "completed"]


def qa_outcome() -> QaRunOutcome:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return QaRunOutcome(
        status=QaRunStatus.FAILED,
        started_at=now,
        finished_at=now,
        duration_ms=100,
        tests=[
            TestResult(
                name="Application Reachability",
                status=TestStatus.PASSED,
                duration_ms=10,
                url="http://target.invalid/",
                details={"http_status": 200},
            ),
            TestResult(
                name="Page Title",
                status=TestStatus.FAILED,
                duration_ms=5,
                url="http://target.invalid/",
                error="Page title is missing or empty",
            ),
        ],
        metadata={"browser": "fake"},
    )


def security_outcome() -> SecurityRunOutcome:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return SecurityRunOutcome(
        status=SecurityRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
        duration_ms=200,
        components=[
            ComponentResult(
                name="zap",
                status=ComponentStatus.COMPLETED,
                findings=[
                    SecurityFinding(
                        source="zap",
                        name="CSP Header Not Set",
                        severity=Severity.MEDIUM,
                        rule_id="10038",
                        url="http://target.invalid/",
                        method="GET",
                    ),
                ],
            ),
            ComponentResult(
                name="api_probes",
                status=ComponentStatus.COMPLETED,
                findings=[
                    SecurityFinding(
                        source="api_probe",
                        name="Technology disclosed in X-Powered-By",
                        severity=Severity.LOW,
                        rule_id="api-probe-disclosure-x-powered-by",
                        url="http://target.invalid:9998",
                        method="GET",
                        evidence="x-powered-by: Express",
                    ),
                ],
            ),
            ComponentResult(
                name="semgrep", status=ComponentStatus.SKIPPED, detail="not installed"
            ),
        ],
        engine_metadata={"engine_version": "test"},
    )


class FakeQaEngine:
    def __init__(self, outcome: QaRunOutcome | None = None, exc: Exception | None = None):
        self.outcome, self.exc = outcome, exc
        self.calls: list[str] = []

    def __call__(self, base_url: str, config: Any) -> QaRunOutcome:
        self.calls.append(base_url)
        if self.exc:
            raise self.exc
        return self.outcome


class FakeSecurityEngine:
    def __init__(self, outcome: SecurityRunOutcome | None = None, exc: Exception | None = None):
        self.outcome, self.exc = outcome, exc
        self.calls: list[str] = []

    def __call__(self, *, base_url: str, api_url, source_path, config) -> SecurityRunOutcome:
        self.calls.append(base_url)
        if self.exc:
            raise self.exc
        return self.outcome


def _override_with(client: TestClient, qa_engine, security_engine) -> None:
    from app.api.dependencies import get_assessment_service
    from app.core.config import get_settings
    from app.core.database import get_database
    from app.services.assessment_service import AssessmentService
    from app.services.qa_service import QaService
    from app.services.security_service import SecurityService
    from app.services.target_service import TargetService

    def _override() -> AssessmentService:
        database = get_database()
        settings = get_settings()
        targets = TargetService(database)
        return AssessmentService(
            db=database,
            targets=targets,
            qa=QaService(db=database, targets=targets, settings=settings, engine=qa_engine),
            security=SecurityService(
                db=database, targets=targets, settings=settings, engine=security_engine
            ),
            settings=settings,
        )

    client.app.dependency_overrides[get_assessment_service] = _override


@pytest.fixture
def qa_engine() -> FakeQaEngine:
    return FakeQaEngine(qa_outcome())


@pytest.fixture
def security_engine() -> FakeSecurityEngine:
    return FakeSecurityEngine(security_outcome())


@pytest.fixture
def assess_client(
    client: TestClient, qa_engine: FakeQaEngine, security_engine: FakeSecurityEngine
) -> Iterator[TestClient]:
    """TestClient whose orchestrator uses the real services with fake engines."""
    from app.api.dependencies import get_assessment_service

    _override_with(client, qa_engine, security_engine)
    try:
        yield client
    finally:
        client.app.dependency_overrides.pop(get_assessment_service, None)


@pytest.fixture
def target_cleanup(client: TestClient) -> Iterator[list[str]]:
    created: list[str] = []
    try:
        yield created
    finally:
        for target_id in created:
            client.delete(f"/targets/{target_id}")


@pytest.fixture
def db_cleanup(settings) -> Iterator[dict[str, list[str]]]:
    """Remove everything an assessment wrote, across all four collections."""
    created: dict[str, list[str]] = {"assessments": [], "qa_runs": [], "security_runs": []}
    try:
        yield created
    finally:
        from bson import ObjectId
        from pymongo import MongoClient

        with MongoClient(settings.mongodb_uri) as direct:
            database = direct[settings.mongodb_database]
            if created["assessments"]:
                database["evidence"].delete_many(
                    {"assessment_id": {"$in": created["assessments"]}}
                )
            for collection, ids in created.items():
                if ids:
                    database[collection].delete_many(
                        {"_id": {"$in": [ObjectId(i) for i in ids]}}
                    )


def make_target(client: TestClient, target_cleanup: list[str], **overrides: Any):
    body: dict[str, Any] = {
        "name": f"pytest-assess-target-{uuid4().hex[:10]}",
        "base_url": "http://target.invalid:9999",
        "api_url": "http://target.invalid:9998",
        "type": "web_and_api",
        "source_path": None,
        "description": "Created by the orchestration test suite.",
        "enabled": True,
    }
    body.update(overrides)
    response = client.post("/targets", json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    target_cleanup.append(created["id"])
    return created


def start_assessment(client: TestClient, db_cleanup, target_id: str):
    response = client.post("/assessments", json={"target_id": target_id})
    if response.status_code == 201:
        body = response.json()
        db_cleanup["assessments"].append(body["id"])
        if body.get("qa_run_id"):
            db_cleanup["qa_runs"].append(body["qa_run_id"])
        if body.get("security_run_id"):
            db_cleanup["security_runs"].append(body["security_run_id"])
    return response


def direct_db(settings):
    from pymongo import MongoClient

    client = MongoClient(settings.mongodb_uri, tz_aware=True)
    return client, client[settings.mongodb_database]


# --- orchestration ---------------------------------------------------------


def test_assessment_runs_both_engines_and_returns_201(
    assess_client, client, target_cleanup, db_cleanup, qa_engine, security_engine
) -> None:
    target = make_target(client, target_cleanup)
    response = start_assessment(assess_client, db_cleanup, target["id"])
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["status"] == "completed"
    assert body["qa_status"] == "completed"
    assert body["security_status"] == "completed"
    assert body["partial"] is False
    assert qa_engine.calls == [target["base_url"]]
    assert security_engine.calls == [target["base_url"]]


def test_the_full_lifecycle_is_recorded_in_order(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    body = start_assessment(assess_client, db_cleanup, target["id"]).json()

    history = body["state_history"]
    assert [t["state"] for t in history] == HAPPY_PATH
    assert all(t["message"] and t["timestamp"] for t in history)


def test_assessment_references_raw_runs_and_leaves_them_untouched(
    assess_client, client, target_cleanup, db_cleanup, settings
) -> None:
    from bson import ObjectId

    target = make_target(client, target_cleanup)
    body = start_assessment(assess_client, db_cleanup, target["id"]).json()

    assert assess_client.get(f"/qa/runs/{body['qa_run_id']}").status_code == 200
    assert assess_client.get(f"/security/runs/{body['security_run_id']}").status_code == 200
    assert "tests" not in body and "components" not in body and "evidence" not in body

    mongo, database = direct_db(settings)
    with mongo:
        qa = database["qa_runs"].find_one({"_id": ObjectId(body["qa_run_id"])})
        security = database["security_runs"].find_one(
            {"_id": ObjectId(body["security_run_id"])}
        )
    # The orchestrator added nothing to the raw runs.
    assert "assessment_id" not in qa and "assessment_id" not in security
    assert len(qa["tests"]) == 2
    assert len(security["findings"]) == 2


def test_summary_is_derived_from_the_real_runs(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    summary = start_assessment(assess_client, db_cleanup, target["id"]).json()["summary"]

    assert summary["qa"] == {"total": 2, "passed": 1, "failed": 1, "skipped": 0, "error": 0}
    assert summary["security"] == {
        "total": 2, "high": 0, "medium": 1, "low": 1, "informational": 0,
    }
    assert summary["total_findings"] == 3
    assert summary["evidence_total"] == 4


def test_failing_tests_and_findings_do_not_fail_the_assessment(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    body = start_assessment(assess_client, db_cleanup, target["id"]).json()

    assert body["qa_run_status"] == "failed"
    assert body["qa_status"] == "completed"
    assert body["status"] == "completed"
    assert body["error"] is None


def test_qa_engine_crash_is_recorded_and_security_still_runs(
    client, target_cleanup, db_cleanup, security_engine
) -> None:
    from app.api.dependencies import get_assessment_service

    _override_with(client, FakeQaEngine(exc=RuntimeError("browser would not launch")),
                   security_engine)
    try:
        target = make_target(client, target_cleanup)
        response = start_assessment(client, db_cleanup, target["id"])
        assert response.status_code == 201, response.text

        body = response.json()
        assert body["status"] == "completed"
        assert body["partial"] is True
        assert body["qa_status"] == "failed"
        assert "browser would not launch" in body["qa_error"]
        assert body["qa_run_id"] is None
        assert body["security_status"] == "completed"
        assert security_engine.calls == [target["base_url"]]

        evidence = client.get(f"/assessments/{body['id']}/evidence").json()
        assert {item["finding_type"] for item in evidence} == {"security"}
    finally:
        client.app.dependency_overrides.pop(get_assessment_service, None)


def test_security_engine_crash_is_recorded(
    client, target_cleanup, db_cleanup, qa_engine
) -> None:
    from app.api.dependencies import get_assessment_service

    _override_with(client, qa_engine, FakeSecurityEngine(exc=RuntimeError("ZAP unreachable")))
    try:
        target = make_target(client, target_cleanup)
        body = start_assessment(client, db_cleanup, target["id"]).json()

        assert body["status"] == "completed"
        assert body["partial"] is True
        assert body["security_status"] == "failed"
        assert "ZAP unreachable" in body["security_error"]
        assert body["security_run_id"] is None
        evidence = client.get(f"/assessments/{body['id']}/evidence").json()
        assert {item["finding_type"] for item in evidence} == {"qa"}
    finally:
        client.app.dependency_overrides.pop(get_assessment_service, None)


def test_both_engines_crashing_fails_the_assessment_but_still_records_it(
    client, target_cleanup, db_cleanup
) -> None:
    from app.api.dependencies import get_assessment_service

    _override_with(
        client,
        FakeQaEngine(exc=RuntimeError("no browser")),
        FakeSecurityEngine(exc=RuntimeError("no scanner")),
    )
    try:
        target = make_target(client, target_cleanup)
        response = start_assessment(client, db_cleanup, target["id"])
        # The platform recorded what happened; nothing crashed.
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "failed"
        assert "no browser" in body["error"] and "no scanner" in body["error"]
        assert body["state_history"][-1]["state"] == "failed"
        assert body["evidence_count"] == 0
    finally:
        client.app.dependency_overrides.pop(get_assessment_service, None)


# --- evidence --------------------------------------------------------------


def test_evidence_endpoint_returns_traceable_records_in_order(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    created = start_assessment(assess_client, db_cleanup, target["id"]).json()

    response = assess_client.get(f"/assessments/{created['id']}/evidence")
    assert response.status_code == 200
    evidence = response.json()

    assert len(evidence) == created["evidence_count"] == 4
    assert [item["sequence"] for item in evidence] == [0, 1, 2, 3]
    assert {item["source"] for item in evidence} == {"playwright", "zap", "api_probe"}
    for item in evidence:
        assert item["assessment_id"] == created["id"]
        assert item["source_run_id"] in {created["qa_run_id"], created["security_run_id"]}
        assert item["source_finding_id"]
        if item["finding_type"] == "security":
            assert item["expected"] is None

    probe = next(item for item in evidence if item["source"] == "api_probe")
    assert probe["actual"] == "x-powered-by: Express"
    assert probe["category"] == "information_disclosure"


def test_evidence_limit_is_applied_and_validated(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    created = start_assessment(assess_client, db_cleanup, target["id"]).json()

    limited = assess_client.get(f"/assessments/{created['id']}/evidence?limit=2").json()
    assert [item["sequence"] for item in limited] == [0, 1]
    assert assess_client.get(f"/assessments/{created['id']}/evidence?limit=0").status_code == 422


def test_evidence_is_really_in_its_own_collection(
    assess_client, client, target_cleanup, db_cleanup, settings
) -> None:
    target = make_target(client, target_cleanup)
    created = start_assessment(assess_client, db_cleanup, target["id"]).json()

    mongo, database = direct_db(settings)
    with mongo:
        stored = list(database["evidence"].find({"assessment_id": created["id"]}))
    assert len(stored) == 4
    assert all(hasattr(item["timestamp"], "year") for item in stored)
    assert all(item["evidence_id"] for item in stored)


# --- validation ------------------------------------------------------------


def _assessment_count(settings, target_id: str) -> int:
    mongo, database = direct_db(settings)
    with mongo:
        return database["assessments"].count_documents({"target_id": target_id})


def test_disabled_target_is_rejected_and_nothing_is_created(
    assess_client, client, target_cleanup, db_cleanup, qa_engine, settings
) -> None:
    target = make_target(client, target_cleanup, enabled=False)
    response = start_assessment(assess_client, db_cleanup, target["id"])
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]
    assert qa_engine.calls == []
    assert _assessment_count(settings, target["id"]) == 0


def test_api_only_target_is_rejected(
    assess_client, client, target_cleanup, db_cleanup, settings
) -> None:
    target = make_target(client, target_cleanup, type="api")
    response = start_assessment(assess_client, db_cleanup, target["id"])
    assert response.status_code == 409
    assert "web target" in response.json()["detail"]
    assert _assessment_count(settings, target["id"]) == 0


def test_unknown_target_is_404(assess_client, db_cleanup) -> None:
    assert start_assessment(assess_client, db_cleanup, MISSING_ID).status_code == 404


def test_malformed_target_id_is_400(assess_client, db_cleanup) -> None:
    assert start_assessment(assess_client, db_cleanup, "nope").status_code == 400


def test_caller_cannot_supply_a_url(assess_client, client, target_cleanup) -> None:
    target = make_target(client, target_cleanup)
    response = assess_client.post(
        "/assessments", json={"target_id": target["id"], "url": "https://elsewhere.example"}
    )
    assert response.status_code == 422


def test_missing_target_id_is_422(assess_client) -> None:
    assert assess_client.post("/assessments", json={}).status_code == 422


# --- retrieval -------------------------------------------------------------


def test_get_assessment_returns_the_stored_document(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    created = start_assessment(assess_client, db_cleanup, target["id"]).json()

    response = assess_client.get(f"/assessments/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_assessment_404_and_400(assess_client) -> None:
    assert assess_client.get(f"/assessments/{MISSING_ID}").status_code == 404
    assert assess_client.get("/assessments/nope").status_code == 400
    assert assess_client.get(f"/assessments/{MISSING_ID}/evidence").status_code == 404
    assert assess_client.get("/assessments/nope/evidence").status_code == 400


def test_list_assessments_newest_first(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    older = start_assessment(assess_client, db_cleanup, target["id"]).json()
    newer = start_assessment(assess_client, db_cleanup, target["id"]).json()

    ids = [a["id"] for a in assess_client.get("/assessments").json()]
    assert ids.index(newer["id"]) < ids.index(older["id"])


def test_list_assessments_limit_is_validated(assess_client) -> None:
    assert assess_client.get("/assessments?limit=0").status_code == 422
    assert assess_client.get("/assessments?limit=1000").status_code == 422


def test_target_snapshot_survives_a_rename(
    assess_client, client, target_cleanup, db_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    created = start_assessment(assess_client, db_cleanup, target["id"]).json()

    renamed = client.patch(f"/targets/{target['id']}", json={"name": "renamed later"})
    assert renamed.status_code == 200, renamed.text

    stored = assess_client.get(f"/assessments/{created['id']}").json()
    assert stored["target_name"] == target["name"]


# --- persistence -----------------------------------------------------------


def test_assessment_is_really_a_document_in_mongodb(
    assess_client, client, target_cleanup, db_cleanup, settings
) -> None:
    from bson import ObjectId

    target = make_target(client, target_cleanup)
    created = start_assessment(assess_client, db_cleanup, target["id"]).json()

    mongo, database = direct_db(settings)
    with mongo:
        document = database["assessments"].find_one({"_id": ObjectId(created["id"])})

    assert document is not None
    assert document["status"] == "completed"
    assert document["qa_run_id"] == created["qa_run_id"]
    assert document["security_run_id"] == created["security_run_id"]
    assert [t["state"] for t in document["state_history"]] == HAPPY_PATH
    assert hasattr(document["started_at"], "year")
    assert hasattr(document["finished_at"], "year")
    # Evidence lives in its own collection, not embedded here.
    assert "evidence" not in document
    assert document["evidence_count"] == 4


def test_both_phase_4_indexes_exist(client, settings) -> None:
    mongo, database = direct_db(settings)
    with mongo:
        assessments = database["assessments"].index_information()
        evidence = database["evidence"].index_information()

    assert assessments["assessments_by_target"]["key"] == [("target_id", 1), ("started_at", -1)]
    assert evidence["evidence_by_assessment"]["key"] == [("assessment_id", 1), ("timestamp", -1)]
    assert not assessments["assessments_by_target"].get("unique", False)
    assert not evidence["evidence_by_assessment"].get("unique", False)


# --- real end-to-end -------------------------------------------------------


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.security
@pytest.mark.playwright
def test_real_full_pipeline_against_a_live_target(
    client: TestClient, db_cleanup, settings
) -> None:
    """The whole thing for real: Playwright, ZAP and a live registered target."""
    pytest.importorskip("playwright", reason="Playwright is not installed")
    if not _reachable(settings.zap_host, settings.zap_port):
        pytest.skip(f"ZAP is not running at {settings.zap_host}:{settings.zap_port}")

    live = []
    for target in client.get("/targets").json():
        if not (target["enabled"] and target["base_url"]):
            continue
        if target["type"] not in {"web_application", "web_and_api"}:
            continue
        parsed = urlparse(target["base_url"])
        if parsed.hostname and _reachable(parsed.hostname, parsed.port or 80):
            live.append(target)
    if not live:
        pytest.skip("no registered, enabled web target is currently reachable")

    response = start_assessment(client, db_cleanup, live[0]["id"])
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "completed", body.get("error")
    assert body["qa_status"] == "completed", body.get("qa_error")
    assert body["security_status"] == "completed", body.get("security_error")
    assert [t["state"] for t in body["state_history"]] == HAPPY_PATH

    # A stage can execute while one of its scanners fails, so check that ZAP
    # itself really ran - a ZAP outage must never pass as a real scan.
    coverage = {item["source"]: item for item in body["security_coverage"]}
    assert coverage["zap"]["status"] == "completed", coverage["zap"].get("detail")

    evidence = client.get(f"/assessments/{body['id']}/evidence").json()
    assert len(evidence) == body["evidence_count"] > 0
    assert "playwright" in {item["source"] for item in evidence}
    assert {"qa", "security"} == {item["finding_type"] for item in evidence}
