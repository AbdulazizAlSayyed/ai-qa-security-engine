"""Security service and API tests.

Most tests inject a fake engine so the suite never depends on ZAP, Semgrep
or a live target. The last test is the real thing: it drives the actual
engine against a registered target and skips itself when ZAP is not running.
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

from app.engines.security.models import (
    ComponentResult,
    ComponentStatus,
    RunStatus,
    SecurityFinding,
    SecurityRunOutcome,
    Severity,
)

pytestmark = pytest.mark.integration

MISSING_ID = "0" * 24


# --- fakes -------------------------------------------------------------


def make_outcome(
    *,
    status: RunStatus = RunStatus.COMPLETED,
    components: list[ComponentResult] | None = None,
    error: str | None = None,
) -> SecurityRunOutcome:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if components is None:
        components = [
            ComponentResult(
                name="zap",
                status=ComponentStatus.COMPLETED,
                duration_ms=10,
                findings=[
                    SecurityFinding(
                        source="zap",
                        name="Content Security Policy Header Not Set",
                        severity=Severity.MEDIUM,
                        rule_id="10038",
                        url="http://target.invalid/",
                    )
                ],
                metadata={"zap_version": "2.17.0"},
            ),
            ComponentResult(
                name="api_probes", status=ComponentStatus.SKIPPED, detail="no api_url"
            ),
        ]
    return SecurityRunOutcome(
        status=status,
        started_at=now,
        finished_at=now,
        duration_ms=456,
        components=components,
        engine_metadata={"engine_version": "test", "scan_profile": "baseline"},
        error=error,
    )


class RecordingEngine:
    """Stands in for the security engine and remembers how it was called."""

    def __init__(self, outcome: SecurityRunOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        base_url: str,
        api_url: str | None,
        source_path: str | None,
        config: Any,
        authorization_readiness: Any = None,
    ) -> SecurityRunOutcome:
        self.calls.append(
            {
                "authorization_readiness": authorization_readiness,
                "base_url": base_url,
                "api_url": api_url,
                "source_path": source_path,
                "config": config,
            }
        )
        return self.outcome


# --- fixtures ----------------------------------------------------------


@pytest.fixture
def engine() -> RecordingEngine:
    return RecordingEngine(make_outcome())


def _build_client(
    client: TestClient, engine: RecordingEngine, **settings_overrides: Any
) -> Iterator[TestClient]:
    from app.api.dependencies import get_security_service
    from app.core.config import Settings, get_settings
    from app.core.database import get_database
    from app.services.security_service import SecurityService
    from app.services.target_service import TargetService

    base = get_settings()
    settings = (
        Settings(**{**base.model_dump(), **settings_overrides})
        if settings_overrides
        else base
    )

    def _override() -> SecurityService:
        database = get_database()
        return SecurityService(
            db=database,
            targets=TargetService(database),
            settings=settings,
            engine=engine,
        )

    client.app.dependency_overrides[get_security_service] = _override
    try:
        yield client
    finally:
        client.app.dependency_overrides.pop(get_security_service, None)


@pytest.fixture
def sec_client(client: TestClient, engine: RecordingEngine) -> Iterator[TestClient]:
    yield from _build_client(client, engine)


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
    created: list[str] = []
    try:
        yield created
    finally:
        if created:
            from bson import ObjectId
            from pymongo import MongoClient

            with MongoClient(settings.mongodb_uri) as direct:
                direct[settings.mongodb_database]["security_runs"].delete_many(
                    {"_id": {"$in": [ObjectId(run_id) for run_id in created]}}
                )


def make_target(
    client: TestClient, target_cleanup: list[str], **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"pytest-sec-target-{uuid4().hex[:10]}",
        "base_url": "http://target.invalid:9999",
        "api_url": None,
        "type": "web_application",
        "source_path": None,
        "description": "Created by the security test suite.",
        "enabled": True,
    }
    body.update(overrides)
    response = client.post("/targets", json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    target_cleanup.append(created["id"])
    return created


def start_scan(sec_client: TestClient, run_cleanup: list[str], target_id: str):
    response = sec_client.post("/security/runs", json={"target_id": target_id})
    if response.status_code == 201:
        run_cleanup.append(response.json()["id"])
    return response


# --- execution ---------------------------------------------------------


def test_scan_returns_201_and_the_stored_run(
    sec_client, client, target_cleanup, run_cleanup
) -> None:
    target = make_target(client, target_cleanup)

    response = start_scan(sec_client, run_cleanup, target["id"])
    assert response.status_code == 201, response.text

    run = response.json()
    assert len(run["id"]) == 24
    assert run["target_id"] == target["id"]
    assert run["target_name"] == target["name"]
    assert run["target_base_url"] == target["base_url"]
    assert run["status"] == "completed"
    assert run["summary"]["medium"] == 1
    assert run["summary"]["total_findings"] == 1


def test_engine_receives_only_registry_data(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    """The caller supplies an id; every URL comes from the registry."""
    target = make_target(
        client,
        target_cleanup,
        base_url="http://registered.invalid:1234",
        api_url="http://registered.invalid:5678",
        source_path="C:/some/source",
        type="web_and_api",
    )

    start_scan(sec_client, run_cleanup, target["id"])

    assert len(engine.calls) == 1
    call = engine.calls[0]
    assert call["base_url"] == "http://registered.invalid:1234"
    assert call["api_url"] == "http://registered.invalid:5678"
    assert call["source_path"] == "C:/some/source"


def test_caller_cannot_override_the_scanned_url(sec_client, client, target_cleanup) -> None:
    """A URL in the request body must be rejected, not honoured."""
    target = make_target(client, target_cleanup)
    response = sec_client.post(
        "/security/runs",
        json={"target_id": target["id"], "url": "https://not-authorised.example"},
    )
    assert response.status_code == 422


def test_a_vulnerable_target_still_returns_201(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    """Findings are evidence, never HTTP errors."""
    engine.outcome = make_outcome(
        components=[
            ComponentResult(
                name="zap",
                status=ComponentStatus.COMPLETED,
                findings=[
                    SecurityFinding(source="zap", name="SQL Injection", severity=Severity.HIGH),
                    SecurityFinding(source="zap", name="XSS", severity=Severity.HIGH),
                ],
            )
        ]
    )
    target = make_target(client, target_cleanup)

    response = start_scan(sec_client, run_cleanup, target["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["summary"]["high"] == 2
    assert body["findings"][0]["severity"] == "high"


def test_a_failed_scanner_is_persisted_as_a_failed_run(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    engine.outcome = make_outcome(
        status=RunStatus.FAILED,
        components=[
            ComponentResult(
                name="zap",
                status=ComponentStatus.FAILED,
                detail="ZAP API not reachable at http://127.0.0.1:8090",
            )
        ],
    )
    target = make_target(client, target_cleanup)

    response = start_scan(sec_client, run_cleanup, target["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["components"][0]["status"] == "failed"
    assert "not reachable" in body["components"][0]["detail"]


def test_an_engine_error_is_persisted_with_its_reason(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    engine.outcome = make_outcome(
        status=RunStatus.ERROR, components=[], error="RuntimeError: engine exploded"
    )
    target = make_target(client, target_cleanup)

    response = start_scan(sec_client, run_cleanup, target["id"])
    assert response.status_code == 201
    assert response.json()["status"] == "error"
    assert "exploded" in response.json()["error"]


def test_skipped_components_round_trip_with_their_reason(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    engine.outcome = make_outcome(
        components=[
            ComponentResult(
                name="authorization_probes",
                status=ComponentStatus.SKIPPED,
                detail="No authorized authentication configuration is registered",
            ),
            ComponentResult(
                name="semgrep",
                status=ComponentStatus.SKIPPED,
                detail="Semgrep is not installed",
            ),
        ]
    )
    target = make_target(client, target_cleanup)

    body = start_scan(sec_client, run_cleanup, target["id"]).json()
    assert body["status"] == "completed"
    by_name = {c["name"]: c for c in body["components"]}
    assert "authorized" in by_name["authorization_probes"]["detail"]
    assert "not installed" in by_name["semgrep"]["detail"]


# --- target validation -------------------------------------------------


def test_scan_of_a_disabled_target_is_rejected(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    target = make_target(client, target_cleanup, enabled=False)

    response = start_scan(sec_client, run_cleanup, target["id"])
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]
    assert engine.calls == [], "the engine must not scan a disabled target"


def test_scan_of_an_api_only_target_is_rejected(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    target = make_target(client, target_cleanup, type="api")

    response = start_scan(sec_client, run_cleanup, target["id"])
    assert response.status_code == 409
    assert "web target" in response.json()["detail"]
    assert engine.calls == []


def test_scan_of_a_target_without_a_base_url_is_rejected(
    sec_client, client, target_cleanup, run_cleanup, engine
) -> None:
    target = make_target(client, target_cleanup, base_url=None)

    response = start_scan(sec_client, run_cleanup, target["id"])
    assert response.status_code == 409
    assert "base_url" in response.json()["detail"]
    assert engine.calls == []


def test_scan_is_rejected_when_the_security_engine_is_switched_off(
    client, target_cleanup, run_cleanup, engine
) -> None:
    target = make_target(client, target_cleanup)

    for scoped in _build_client(client, engine, security_enabled=False):
        response = start_scan(scoped, run_cleanup, target["id"])
        assert response.status_code == 409
        assert "SECURITY_ENABLED=false" in response.json()["detail"]
        assert engine.calls == []


def test_scan_of_an_unknown_target_is_404(sec_client, run_cleanup) -> None:
    assert start_scan(sec_client, run_cleanup, MISSING_ID).status_code == 404


def test_scan_with_a_malformed_target_id_is_400(sec_client, run_cleanup) -> None:
    response = start_scan(sec_client, run_cleanup, "not-an-objectid")
    assert response.status_code == 400
    assert "not a valid target id" in response.json()["detail"]


def test_scan_without_a_target_id_is_422(sec_client) -> None:
    assert sec_client.post("/security/runs", json={}).status_code == 422


# --- retrieval ---------------------------------------------------------


def test_get_run_returns_the_stored_run(
    sec_client, client, target_cleanup, run_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    created = start_scan(sec_client, run_cleanup, target["id"]).json()

    response = sec_client.get(f"/security/runs/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_run_returns_404_for_an_unknown_id(sec_client) -> None:
    assert sec_client.get(f"/security/runs/{MISSING_ID}").status_code == 404


@pytest.mark.parametrize("bad_id", ["not-an-objectid", "123"])
def test_get_run_returns_400_for_a_malformed_id(sec_client, bad_id) -> None:
    response = sec_client.get(f"/security/runs/{bad_id}")
    assert response.status_code == 400
    assert "not a valid security run id" in response.json()["detail"]


def test_list_runs_returns_newest_first(
    sec_client, client, target_cleanup, run_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    older = start_scan(sec_client, run_cleanup, target["id"]).json()
    newer = start_scan(sec_client, run_cleanup, target["id"]).json()

    ids = [run["id"] for run in sec_client.get("/security/runs").json()]
    assert older["id"] in ids and newer["id"] in ids
    assert ids.index(newer["id"]) < ids.index(older["id"])


def test_list_runs_respects_the_limit(
    sec_client, client, target_cleanup, run_cleanup
) -> None:
    target = make_target(client, target_cleanup)
    start_scan(sec_client, run_cleanup, target["id"])
    start_scan(sec_client, run_cleanup, target["id"])
    assert len(sec_client.get("/security/runs?limit=1").json()) == 1


def test_list_runs_rejects_an_out_of_range_limit(sec_client) -> None:
    assert sec_client.get("/security/runs?limit=0").status_code == 422
    assert sec_client.get("/security/runs?limit=5000").status_code == 422


# --- persistence -------------------------------------------------------


def test_run_is_really_a_document_in_mongodb(
    sec_client, client, target_cleanup, run_cleanup, settings
) -> None:
    """Read the raw document with an independent synchronous driver."""
    from bson import ObjectId
    from pymongo import MongoClient

    target = make_target(client, target_cleanup)
    created = start_scan(sec_client, run_cleanup, target["id"]).json()

    with MongoClient(settings.mongodb_uri, tz_aware=True) as direct:
        document = direct[settings.mongodb_database]["security_runs"].find_one(
            {"_id": ObjectId(created["id"])}
        )

    assert document is not None, "the security run was not persisted"
    assert document["target_id"] == target["id"]
    assert document["status"] == "completed"
    assert document["summary"]["total_findings"] == 1
    assert isinstance(document["components"], list) and document["components"]
    assert hasattr(document["started_at"], "year")


# --- real scanners -----------------------------------------------------


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _url_reachable(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    return _reachable(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))


@pytest.mark.security
def test_real_security_scan_against_a_live_registered_target(
    client: TestClient, run_cleanup, settings, e2e_web_target
) -> None:
    """End-to-end with the real engine, real ZAP and a real target.

    ``e2e_web_target`` (tests/conftest.py) supplies the target and skips when
    none is reachable. ZAP is checked separately, because a missing scanner
    and a missing target are different gaps and must be reported as such.
    This stays a baseline scan - nothing here enables active scanning.
    """
    if not _reachable(settings.zap_host, settings.zap_port):
        pytest.skip(
            f"OWASP ZAP is not running at {settings.zap_host}:{settings.zap_port}"
        )

    target = e2e_web_target
    response = client.post("/security/runs", json={"target_id": target["id"]})
    assert response.status_code == 201, response.text

    run = response.json()
    run_cleanup.append(run["id"])

    assert run["status"] in {"completed", "failed"}
    assert run["target_base_url"] == target["base_url"]

    by_name = {c["name"]: c for c in run["components"]}
    assert "zap" in by_name
    zap = by_name["zap"]
    assert zap["status"] == "completed", zap.get("detail")
    assert zap["metadata"]["zap_version"], "a real ZAP must report its version"

    # Authorization probing must never silently claim to have run.
    assert by_name["authorization_probes"]["status"] == "skipped"

    # Every finding carries the normalized vocabulary.
    for finding in run["findings"]:
        assert finding["severity"] in {"high", "medium", "low", "informational"}
        assert finding["source"] in {"zap", "api_probe", "semgrep"}

    assert client.get(f"/security/runs/{run['id']}").status_code == 200
