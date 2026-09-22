"""Health endpoint tests, including the degraded path and CORS."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import database
from app.core.config import Settings

VITE_ORIGIN = "http://localhost:5173"


def test_root_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200

    body = response.json()
    assert body["service"]
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"


def test_liveness_never_touches_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode() -> dict[str, Any]:
        raise AssertionError("/health/live must not query MongoDB")

    monkeypatch.setattr(database, "ping", explode)

    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.integration
def test_health_reports_a_connected_database(client: TestClient, settings: Settings) -> None:
    response = client.get("/health")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"]
    assert body["timestamp"]

    db = body["database"]
    assert db["status"] == "connected"
    # The endpoint must report the database it is actually connected to, not
    # a fixed name. test_config.py is what guards the production default.
    assert db["database"] == settings.mongodb_database
    assert db["error"] is None
    assert db["latency_ms"] >= 0
    assert db["server_version"]


def test_health_returns_503_when_mongodb_is_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate an outage. A live API over a dead database is not healthy."""

    async def unavailable() -> dict[str, Any]:
        return {
            "status": "unavailable",
            "database": "ai_qa_security",
            "latency_ms": 3000.0,
            "server_version": None,
            "error": "ServerSelectionTimeoutError: simulated outage",
        }

    monkeypatch.setattr(database, "ping", unavailable)

    response = client.get("/health")
    assert response.status_code == 503

    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"]["status"] == "unavailable"
    assert "simulated outage" in body["database"]["error"]


def test_cors_preflight_allows_the_vite_dev_server(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": VITE_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == VITE_ORIGIN


def test_cors_does_not_allow_an_unknown_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
