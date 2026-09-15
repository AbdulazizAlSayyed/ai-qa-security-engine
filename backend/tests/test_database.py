"""MongoDB connectivity tests against the real local server."""

from __future__ import annotations

import pytest

from app.core import database
from app.core.config import Settings


async def test_get_client_raises_a_clear_error_before_startup() -> None:
    await database.close_mongo_connection()
    with pytest.raises(RuntimeError, match="not initialised"):
        database.get_client()


@pytest.mark.integration
async def test_ping_reaches_the_configured_mongodb(mongo: None) -> None:
    result = await database.ping()

    assert result["status"] == "connected", result["error"]
    assert result["error"] is None
    assert result["latency_ms"] is not None and result["latency_ms"] >= 0
    assert result["server_version"], "buildInfo should report a version string"


@pytest.mark.integration
async def test_get_database_returns_the_configured_database(
    mongo: None, settings: Settings
) -> None:
    assert database.get_database().name == settings.mongodb_database


@pytest.mark.integration
async def test_documents_round_trip_through_mongodb(mongo: None) -> None:
    """Prove writes actually persist, not just that a socket opened."""
    collection = database.get_database()["_phase0_smoke"]
    try:
        inserted = await collection.insert_one({"phase": 0, "check": "read-write"})
        fetched = await collection.find_one({"_id": inserted.inserted_id})

        assert fetched is not None
        assert fetched["check"] == "read-write"
        assert fetched["phase"] == 0
    finally:
        await collection.drop()


async def test_ping_reports_unavailable_instead_of_raising() -> None:
    """A dead database must be describable, not an exception at the route."""
    await database.close_mongo_connection()
    result = await database.ping()

    assert result["status"] == "unavailable"
    assert result["server_version"] is None
    assert "not initialised" in result["error"]
