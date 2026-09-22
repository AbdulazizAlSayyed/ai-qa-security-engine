"""Shared pytest fixtures.

The integration tests here talk to the real MongoDB on the configured URI.
That is deliberate: the point of Phase 0 is proving the chain actually
connects, and a mocked database would prove nothing.

Three kinds of test live in this suite, and they must stay distinguishable:

*fake test*
    An engine or provider is replaced through ``app.dependency_overrides``.
    Nothing outside the process is touched. Most of the suite is this.
*real local integration test*
    Marked ``integration``. Talks to the real MongoDB on the configured URI.
*real target E2E test*
    Marked ``playwright`` and/or ``security``. Drives a real browser or a
    real OWASP ZAP against a running application. :func:`e2e_web_target`
    below is what provisions the target those tests need, so they stop
    depending on whatever a developer happened to leave in the registry.

A fake test never counts as a real verification of anything, and this file
must never blur that line to make a suite look greener than it is.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlparse

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


# --- real target E2E support ------------------------------------------------
#
# The engines are target-agnostic and must stay that way, so nothing here
# knows a page, a selector, a credential or a workflow of any application.
# This fixture only answers one question - "is there a web target registered
# and running that a real E2E test may use?" - and registers one from
# configuration when there is not, so the real tests stop silently skipping
# just because the registry happened to be empty.

#: Where the E2E target is served. Test-harness configuration, deliberately
#: separate from the application's own settings: it describes the machine the
#: suite runs on, not how the platform behaves.
E2E_BASE_URL_VAR = "E2E_TARGET_BASE_URL"
E2E_API_URL_VAR = "E2E_TARGET_API_URL"
DEFAULT_E2E_BASE_URL = "http://localhost:3000"
DEFAULT_E2E_API_URL = "http://localhost:4000"
#: Marks the targets this fixture creates, so teardown removes only its own.
E2E_TARGET_NAME = "pytest-e2e-target"


def url_reachable(url: str, timeout: float = 1.5) -> bool:
    """Can something be connected to at ``url``'s host and port?"""
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def e2e_web_target(client: TestClient) -> Iterator[dict]:
    """A registered, enabled, currently reachable web target.

    Prefers one that is already registered, so a developer's own target is
    used as-is. Otherwise registers one for the URLs in the environment and
    removes it afterwards, leaving the registry exactly as it was found.

    Skips - never fails - when nothing is listening, because a machine with
    no application running cannot answer the question these tests ask.
    """
    for target in client.get("/targets").json():
        if (
            target["enabled"]
            and target["type"] in {"web_application", "web_and_api"}
            and target["base_url"]
            and url_reachable(target["base_url"])
        ):
            yield target
            return

    base_url = os.environ.get(E2E_BASE_URL_VAR, DEFAULT_E2E_BASE_URL)
    api_url = os.environ.get(E2E_API_URL_VAR, DEFAULT_E2E_API_URL)
    if not url_reachable(base_url):
        pytest.skip(
            f"no registered web target is reachable, and nothing is listening at "
            f"{base_url}. Start the application under test, or point "
            f"{E2E_BASE_URL_VAR} at one."
        )

    payload = {
        "name": f"{E2E_TARGET_NAME} {base_url}",
        "base_url": base_url,
        "type": "web_and_api" if url_reachable(api_url) else "web_application",
        "description": "Registered by the pytest E2E fixture. Safe to delete.",
    }
    if url_reachable(api_url):
        payload["api_url"] = api_url

    response = client.post("/targets", json=payload)
    if response.status_code == 409:
        # A previous run left it behind; reuse it rather than duplicating.
        existing = [t for t in client.get("/targets").json() if t["name"] == payload["name"]]
        if not existing:
            pytest.skip(f"target {payload['name']!r} conflicts but cannot be found")
        yield existing[0]
        return
    assert response.status_code == 201, response.text

    target = response.json()
    try:
        yield target
    finally:
        client.delete(f"/targets/{target['id']}")
