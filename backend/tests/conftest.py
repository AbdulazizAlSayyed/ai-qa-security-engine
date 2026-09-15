"""Shared pytest fixtures.

The integration tests here talk to the real MongoDB on the configured URI.
That is deliberate: the point of Phase 0 is proving the chain actually
connects, and a mocked database would prove nothing.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Allow `import app...` when pytest is invoked from the project root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import database  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient running the real lifespan, so MongoDB is wired up.

    Entering the context manager triggers startup and leaving it triggers
    shutdown, which also resets the module-level client back to None.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def mongo() -> AsyncIterator[None]:
    """Connect the shared client inside the running test's event loop."""
    await database.close_mongo_connection()
    await database.connect_to_mongo()
    try:
        yield
    finally:
        await database.close_mongo_connection()
