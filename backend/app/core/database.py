"""MongoDB connection lifecycle.

The backend talks to MongoDB through PyMongo's native async client
(``pymongo.AsyncMongoClient``). Motor is deliberately not used: it reached
end of life in May 2026 and its async functionality now lives inside
PyMongo itself.

Creating the client performs no I/O -- PyMongo connects lazily and monitors
the topology in the background -- so a MongoDB that is down never prevents
the API process from starting. An outage surfaces through :func:`ping`,
which is exactly what the /health endpoint is for.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_MAX_ERROR_CHARS = 300

_client: AsyncMongoClient | None = None
# buildInfo does not change while a connection is alive, so the version is
# fetched once and reused instead of costing a round trip on every /health.
_server_version: str | None = None


async def connect_to_mongo() -> AsyncMongoClient:
    """Create the shared client. Idempotent; called on application startup."""
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    _client = AsyncMongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
        connectTimeoutMS=settings.mongodb_timeout_ms,
        appname="ai-qa-security-engine",
        # BSON dates carry no timezone. Without this, stored timestamps read
        # back as naive datetimes and would serialise without the trailing Z,
        # so clients could not tell they are UTC.
        tz_aware=True,
    )
    logger.info(
        "MongoDB client created (uri=%s, database=%s)",
        settings.mongodb_uri,
        settings.mongodb_database,
    )
    return _client


async def close_mongo_connection() -> None:
    """Tear down the shared client. Safe to call when nothing is open."""
    global _client, _server_version
    client, _client, _server_version = _client, None, None
    if client is None:
        return
    try:
        await client.close()
    except Exception as exc:  # pragma: no cover - defensive teardown
        logger.warning("Error while closing MongoDB client: %s", exc)
    else:
        logger.info("MongoDB client closed")


def get_client() -> AsyncMongoClient:
    """Return the live client, or explain why there isn't one."""
    if _client is None:
        raise RuntimeError(
            "MongoDB client is not initialised. "
            "connect_to_mongo() runs during application startup."
        )
    return _client


def get_database() -> AsyncDatabase:
    """Return the configured application database."""
    return get_client()[get_settings().mongodb_database]


def _failure(database: str, latency_ms: float, error: str) -> dict[str, Any]:
    if len(error) > _MAX_ERROR_CHARS:
        error = error[:_MAX_ERROR_CHARS] + "..."
    return {
        "status": "unavailable",
        "database": database,
        "latency_ms": latency_ms,
        "server_version": None,
        "error": error,
    }


async def ping() -> dict[str, Any]:
    """Round-trip a real command to MongoDB and report what happened.

    Returns a plain dict rather than raising, because the health endpoint
    needs to *describe* an outage, not blow up on one.
    """
    global _server_version

    database = get_settings().mongodb_database
    started = time.perf_counter()

    try:
        client = get_client()
    except RuntimeError as exc:
        return _failure(database, 0.0, str(exc))

    try:
        await client.admin.command("ping")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        if _server_version is None:
            build_info = await client.admin.command("buildInfo")
            _server_version = str(build_info.get("version", "unknown"))

        return {
            "status": "connected",
            "database": database,
            "latency_ms": latency_ms,
            "server_version": _server_version,
            "error": None,
        }
    except PyMongoError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning("MongoDB ping failed after %.2fms: %s", latency_ms, exc)
        return _failure(database, latency_ms, f"{type(exc).__name__}: {exc}")
