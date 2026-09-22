"""QA service and API tests.

Most tests inject a fake engine through ``app.dependency_overrides`` so the
suite never depends on Chromium being installed. The last test in the file
is the real thing: it drives an actual browser against a registered target,
and skips itself when that target is not running.
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

from app.engines.qa.models import (
    ConsoleError,
    NetworkFailure,
    QaRunOutcome,
    RunStatus,
    TestResult,
    TestStatus,
)

pytestmark = pytest.mark.integration

MISSING_ID = "0" * 24


# --- fakes -------------------------------------------------------------


def make_outcome(
    *,
    status: RunStatus = RunStatus.PASSED,
    tests: list[TestResult] | None = None,
    console_errors: list[ConsoleError] | None = None,
    network_failures: list[NetworkFailure] | None = None,
    error: str | None = None,
) -> QaRunOutcome:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if tests is None:
        tests = [
            TestResult(
                name="Application Reachability",
                status=TestStatus.PASSED,
                duration_ms=10,
                url="http://target.invalid/",
                title="Fake Target",
                details={"http_status": 200},
            )
        ]
    return QaRunOutcome(
        status=status,
        started_at=now,
        finished_at=now,
        duration_ms=123,
        tests=tests,
        console_errors=console_errors or [],
        network_failures=network_failures or [],
        metadata={"browser": "fake", "engine_version": "test"},
        error=error,
    )


class RecordingEngine:
    """Stands in for the Playwright runner and remembers how it was called."""

    def __init__(self, outcome: QaRunOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, Any]] = []

    def __call__(self, base_url: str, config: Any) -> QaRunOutcome:
        self.calls.append((base_url, config))
        return self.outcome


# --- fixtures ----------------------------------------------------------


@pytest.fixture
def engine() -> RecordingEngine:
    return RecordingEngine(make_outcome())


@pytest.fixture
def qa_client(client: TestClient, engine: RecordingEngine) -> Iterator[TestClient]:
    """TestClient whose QA service uses the fake engine."""
    from app.api.dependencies import get_qa_service
    from app.core.config import get_settings
    from app.core.database import get_database
    from app.services.qa_service import QaService
    from app.services.target_service import TargetService

    def _override() -> QaService:
        database = get_database()
        return QaService(
            db=database,
            targets=TargetService(database),
            settings=get_settings(),
            engine=engine,
        )

    client.app.dependency_overrides[get_qa_service] = _override
    try:
        yield client
    finally:
        client.app.dependency_overrides.pop(get_qa_service, None)


@pytest.fixture
def target_cleanup(client: TestClient) -> Iterator[list[str]]:
    created: list[str] = []
    try:
        yield created
    finally:
        for target_id in created:
            client.delete(f"/targets/{target_id}")


@pytest.fixture
def run_cleanup(settings) -> Iterator[list[str]]:
    """Remove QA runs the tests created, leaving real history alone."""
    created: list[str] = []
    try:
        yield created
    finally:
        if created:
            from bson import ObjectId
            from pymongo import MongoClient

            with MongoClient(settings.mongodb_uri) as direct:
                direct[settings.mongodb_database]["qa_runs"].delete_many(
                    {"_id": {"$in": [ObjectId(run_id) for run_id in created]}}
                )


def make_target(
    client: TestClient, target_cleanup: list[str], **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"pytest-qa-target-{uuid4().hex[:10]}",
        "base_url": "http://target.invalid:9999",
        "api_url": None,
        "type": "web_application",
        "source_path": None,
        "description": "Created by the QA test suite.",
        "enabled": True,
    }
    body.update(overrides)
    response = client.post("/targets", json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    target_cleanup.append(created["id"])
    return created


def start_run(
    qa_client: TestClient, run_cleanup: list[str], target_id: str
) -> Any:
    response = qa_client.post("/qa/runs", json={"target_id": target_id})
    if response.status_code == 201:
        run_cleanup.append(response.json()["id"])
    return response


# --- execution ---------------------------------------------------------


def test_run_returns_201_and_the_stored_run(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    target = make_target(client, target_cleanup)

    response = start_run(qa_client, run_cleanup, target["id"])
    assert response.status_code == 201, response.text

    run = response.json()
    assert len(run["id"]) == 24
    assert run["target_id"] == target["id"]
    assert run["target_name"] == target["name"]
    assert run["target_base_url"] == target["base_url"]
    assert run["status"] == "passed"
    assert run["tests"][0]["name"] == "Application Reachability"
    assert run["duration_ms"] == 123


def test_engine_is_given_the_targets_own_base_url(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    """The engine must never be handed anything but the registered URL."""
    target = make_target(client, target_cleanup, base_url="http://elsewhere.invalid:1234")

    start_run(qa_client, run_cleanup, target["id"])

    assert len(engine.calls) == 1
    assert engine.calls[0][0] == "http://elsewhere.invalid:1234"


def test_engine_receives_the_configured_timeouts(
    qa_client, target_cleanup, run_cleanup, engine, client, settings
) -> None:
    target = make_target(client, target_cleanup)
    start_run(qa_client, run_cleanup, target["id"])

    config = engine.calls[0][1]
    assert config.navigation_timeout_ms == settings.qa_navigation_timeout_ms
    assert config.test_timeout_ms == settings.qa_test_timeout_ms


def test_a_failing_application_is_persisted_not_rejected(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    """A broken target is a result, not an API error."""
    engine.outcome = make_outcome(
        status=RunStatus.FAILED,
        tests=[
            TestResult(
                name="Application Reachability",
                status=TestStatus.FAILED,
                duration_ms=5,
                error="Navigating to http://target.invalid returned HTTP 500",
            )
        ],
    )
    target = make_target(client, target_cleanup)

    response = start_run(qa_client, run_cleanup, target["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert "HTTP 500" in body["tests"][0]["error"]


def test_an_engine_error_is_persisted_with_its_reason(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    """Playwright being unavailable must be recorded, not silently lost."""
    engine.outcome = make_outcome(
        status=RunStatus.ERROR,
        tests=[],
        error="Playwright is not installed in the backend environment",
    )
    target = make_target(client, target_cleanup)

    response = start_run(qa_client, run_cleanup, target["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "error"
    assert "Playwright" in body["error"]


def test_observations_round_trip(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    engine.outcome = make_outcome(
        console_errors=[
            ConsoleError(type="console_error", message="boom", location="app.js:10:5")
        ],
        network_failures=[
            NetworkFailure(url="http://t/api", method="GET", status=500),
            NetworkFailure(url="http://t/x", method="POST", failure="ERR_ABORTED"),
        ],
    )
    target = make_target(client, target_cleanup)

    body = start_run(qa_client, run_cleanup, target["id"]).json()

    assert body["console_errors"][0]["message"] == "boom"
    assert body["console_errors"][0]["location"] == "app.js:10:5"
    assert body["network_failures"][0]["status"] == 500
    assert body["network_failures"][1]["failure"] == "ERR_ABORTED"


# --- target validation -------------------------------------------------


def test_run_against_a_disabled_target_is_rejected(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    target = make_target(client, target_cleanup, enabled=False)

    response = start_run(qa_client, run_cleanup, target["id"])
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]
    assert engine.calls == [], "the engine must not run against a disabled target"


def test_run_against_an_api_only_target_is_rejected(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    target = make_target(client, target_cleanup, type="api")

    response = start_run(qa_client, run_cleanup, target["id"])
    assert response.status_code == 409
    assert "web target" in response.json()["detail"]
    assert engine.calls == []


def test_web_and_api_targets_are_supported(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    target = make_target(client, target_cleanup, type="web_and_api")
    assert start_run(qa_client, run_cleanup, target["id"]).status_code == 201


def test_run_against_a_target_without_a_base_url_is_rejected(
    qa_client, target_cleanup, run_cleanup, engine, client
) -> None:
    target = make_target(client, target_cleanup, base_url=None)

    response = start_run(qa_client, run_cleanup, target["id"])
    assert response.status_code == 409
    assert "base_url" in response.json()["detail"]
    assert engine.calls == []


def test_run_against_an_unknown_target_is_404(qa_client, run_cleanup) -> None:
    response = start_run(qa_client, run_cleanup, MISSING_ID)
    assert response.status_code == 404


def test_run_with_a_malformed_target_id_is_400(qa_client, run_cleanup) -> None:
    response = start_run(qa_client, run_cleanup, "not-an-objectid")
    assert response.status_code == 400
    assert "not a valid target id" in response.json()["detail"]


def test_run_without_a_target_id_is_422(qa_client) -> None:
    assert qa_client.post("/qa/runs", json={}).status_code == 422


def test_run_rejects_unknown_fields(qa_client, client, target_cleanup) -> None:
    target = make_target(client, target_cleanup)
    response = qa_client.post(
        "/qa/runs", json={"target_id": target["id"], "suite": "everything"}
    )
    assert response.status_code == 422


# --- retrieval ---------------------------------------------------------


def test_get_run_returns_the_stored_run(
    qa_client, target_cleanup, run_cleanup, client
) -> None:
    target = make_target(client, target_cleanup)
    created = start_run(qa_client, run_cleanup, target["id"]).json()

    response = qa_client.get(f"/qa/runs/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_run_returns_404_for_an_unknown_id(qa_client) -> None:
    assert qa_client.get(f"/qa/runs/{MISSING_ID}").status_code == 404


@pytest.mark.parametrize("bad_id", ["not-an-objectid", "123"])
def test_get_run_returns_400_for_a_malformed_id(qa_client, bad_id: str) -> None:
    response = qa_client.get(f"/qa/runs/{bad_id}")
    assert response.status_code == 400
    assert "not a valid QA run id" in response.json()["detail"]


def test_list_runs_returns_newest_first(
    qa_client, target_cleanup, run_cleanup, client
) -> None:
    target = make_target(client, target_cleanup)
    older = start_run(qa_client, run_cleanup, target["id"]).json()
    newer = start_run(qa_client, run_cleanup, target["id"]).json()

    listed = qa_client.get("/qa/runs")
    assert listed.status_code == 200

    ids = [run["id"] for run in listed.json()]
    assert older["id"] in ids and newer["id"] in ids
    assert ids.index(newer["id"]) < ids.index(older["id"])


def test_list_runs_respects_the_limit(
    qa_client, target_cleanup, run_cleanup, client
) -> None:
    target = make_target(client, target_cleanup)
    start_run(qa_client, run_cleanup, target["id"])
    start_run(qa_client, run_cleanup, target["id"])

    assert len(qa_client.get("/qa/runs?limit=1").json()) == 1


def test_list_runs_rejects_an_out_of_range_limit(qa_client) -> None:
    assert qa_client.get("/qa/runs?limit=0").status_code == 422
    assert qa_client.get("/qa/runs?limit=5000").status_code == 422


# --- persistence -------------------------------------------------------


def test_run_is_really_a_document_in_mongodb(
    qa_client, target_cleanup, run_cleanup, client, settings
) -> None:
    """Read the raw document with an independent synchronous driver."""
    from bson import ObjectId
    from pymongo import MongoClient

    target = make_target(client, target_cleanup)
    created = start_run(qa_client, run_cleanup, target["id"]).json()

    with MongoClient(settings.mongodb_uri, tz_aware=True) as direct:
        document = direct[settings.mongodb_database]["qa_runs"].find_one(
            {"_id": ObjectId(created["id"])}
        )

    assert document is not None, "the QA run was not persisted"
    assert document["target_id"] == target["id"]
    assert document["status"] == "passed"
    assert isinstance(document["tests"], list) and document["tests"]
    # Real BSON dates, not strings.
    assert hasattr(document["started_at"], "year")
    assert hasattr(document["finished_at"], "year")


# --- real browser ------------------------------------------------------


def _reachable(url: str, timeout: float = 1.5) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.playwright
def test_real_playwright_run_against_a_live_registered_target(
    client: TestClient, run_cleanup
) -> None:
    """End-to-end with a real browser, using the real engine.

    Skips rather than fails when the registered target is not running, so
    the suite stays green on a machine where nothing is served locally.
    """
    pytest.importorskip("playwright", reason="Playwright is not installed")

    targets = client.get("/targets").json()
    live = [
        target
        for target in targets
        if target["enabled"]
        and target["type"] in {"web_application", "web_and_api"}
        and target["base_url"]
        and _reachable(target["base_url"])
    ]
    if not live:
        pytest.skip("no registered, enabled web target is currently reachable")

    target = live[0]
    response = client.post("/qa/runs", json={"target_id": target["id"]})
    assert response.status_code == 201, response.text

    run = response.json()
    run_cleanup.append(run["id"])

    assert run["status"] in {"passed", "failed"}, (
        f"engine error against {target['base_url']}: {run.get('error')}"
    )
    assert run["target_base_url"] == target["base_url"]
    assert run["metadata"]["playwright_version"]
    assert run["metadata"]["browser"] == "chromium"

    names = [test["name"] for test in run["tests"]]
    assert names == [
        "Application Reachability",
        "Page Title",
        "DOM Availability",
        "Console Error Collection",
        "Network Failure Collection",
    ]

    reachability = run["tests"][0]
    assert reachability["status"] == "passed", reachability["error"]
    assert reachability["details"]["http_status"] == 200

    # And it is retrievable afterwards.
    assert client.get(f"/qa/runs/{run['id']}").status_code == 200
