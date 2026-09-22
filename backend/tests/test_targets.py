"""Target registry API tests.

These run against the real MongoDB on the configured URI, using the same
TestClient-with-lifespan fixture as Phase 0. Every test names its targets
with a unique suffix and deletes what it created, so the suite never
disturbs real registrations such as Mini E-Commerce.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

# A syntactically valid ObjectId that will not exist in the collection.
MISSING_ID = "0" * 24


@pytest.fixture
def cleanup(client: TestClient) -> Iterator[list[str]]:
    """Delete every target whose id is appended to the yielded list."""
    created: list[str] = []
    try:
        yield created
    finally:
        for target_id in created:
            client.delete(f"/targets/{target_id}")


@pytest.fixture
def payload() -> Callable[..., dict[str, Any]]:
    """Build a valid create payload with a name unique to this test run."""

    def _build(**overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": f"pytest-target-{uuid4().hex[:10]}",
            "base_url": "http://localhost:3000",
            "api_url": "http://localhost:4000",
            "type": "web_application",
            "source_path": None,
            "description": "Created by the automated test suite.",
            "enabled": True,
        }
        body.update(overrides)
        return body

    return _build


def _create(client: TestClient, cleanup: list[str], body: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/targets", json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    cleanup.append(created["id"])
    return created


# --- create -----------------------------------------------------------


def test_create_returns_201_and_the_stored_target(client, cleanup, payload) -> None:
    body = payload()
    created = _create(client, cleanup, body)

    assert len(created["id"]) == 24
    assert created["name"] == body["name"]
    assert created["base_url"] == "http://localhost:3000"
    assert created["api_url"] == "http://localhost:4000"
    assert created["type"] == "web_application"
    assert created["source_path"] is None
    assert created["enabled"] is True
    assert created["created_at"] == created["updated_at"]


def test_create_preserves_urls_without_adding_a_trailing_slash(
    client, cleanup, payload
) -> None:
    """A target's URL must come back exactly as it was registered."""
    created = _create(client, cleanup, payload(base_url="http://localhost:3000"))
    assert created["base_url"] == "http://localhost:3000"


def test_create_applies_defaults_for_optional_fields(client, cleanup, payload) -> None:
    body = payload()
    for optional in ("api_url", "source_path", "description", "enabled", "type"):
        body.pop(optional)

    created = _create(client, cleanup, body)

    assert created["api_url"] is None
    assert created["source_path"] is None
    assert created["description"] == ""
    assert created["enabled"] is True
    assert created["type"] == "web_application"


def test_create_rejects_a_missing_name(client, payload) -> None:
    body = payload()
    del body["name"]
    assert client.post("/targets", json=body).status_code == 422


@pytest.mark.parametrize("name", ["", "   "])
def test_create_rejects_an_empty_name(client, payload, name) -> None:
    assert client.post("/targets", json=payload(name=name)).status_code == 422


@pytest.mark.parametrize("bad_url", ["not-a-url", "localhost:3000", "ftp:/broken"])
def test_create_rejects_an_invalid_base_url(client, payload, bad_url) -> None:
    assert client.post("/targets", json=payload(base_url=bad_url)).status_code == 422


def test_create_rejects_an_unsupported_type(client, payload) -> None:
    assert client.post("/targets", json=payload(type="mainframe")).status_code == 422


def test_create_rejects_client_supplied_protected_fields(client, payload) -> None:
    """created_at is owned by the server, not the client."""
    response = client.post(
        "/targets", json=payload(created_at="2020-01-01T00:00:00Z")
    )
    assert response.status_code == 422


def test_create_rejects_an_exact_duplicate(client, cleanup, payload) -> None:
    body = payload()
    _create(client, cleanup, body)

    response = client.post("/targets", json=body)
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


def test_same_name_with_a_different_api_url_is_not_a_duplicate(
    client, cleanup, payload
) -> None:
    """Two surfaces of one product are legitimately separate targets."""
    body = payload()
    _create(client, cleanup, body)

    second = _create(client, cleanup, {**body, "api_url": "http://localhost:4100"})
    assert second["api_url"] == "http://localhost:4100"


# --- list -------------------------------------------------------------


def test_list_returns_created_targets_newest_first(client, cleanup, payload) -> None:
    older = _create(client, cleanup, payload())
    newer = _create(client, cleanup, payload())

    listed = client.get("/targets")
    assert listed.status_code == 200

    ids = [target["id"] for target in listed.json()]
    assert older["id"] in ids
    assert newer["id"] in ids
    assert ids.index(newer["id"]) < ids.index(older["id"])


# --- get --------------------------------------------------------------


def test_get_returns_an_existing_target(client, cleanup, payload) -> None:
    created = _create(client, cleanup, payload())

    response = client.get(f"/targets/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_returns_404_for_a_valid_but_unknown_id(client) -> None:
    assert client.get(f"/targets/{MISSING_ID}").status_code == 404


@pytest.mark.parametrize("bad_id", ["not-an-objectid", "123", "zzzz" * 6])
def test_get_returns_400_for_a_malformed_object_id(client, bad_id) -> None:
    response = client.get(f"/targets/{bad_id}")
    assert response.status_code == 400
    assert "not a valid target id" in response.json()["detail"]


# --- update -----------------------------------------------------------


def test_update_changes_only_the_supplied_fields(client, cleanup, payload) -> None:
    created = _create(client, cleanup, payload())

    response = client.patch(
        f"/targets/{created['id']}", json={"name": "renamed-by-test", "enabled": False}
    )
    assert response.status_code == 200

    updated = response.json()
    assert updated["name"] == "renamed-by-test"
    assert updated["enabled"] is False
    # Untouched fields survive.
    assert updated["base_url"] == created["base_url"]
    assert updated["api_url"] == created["api_url"]
    # created_at is immutable; updated_at moves forward.
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] >= created["updated_at"]


def test_update_can_clear_an_optional_field_explicitly(client, cleanup, payload) -> None:
    created = _create(client, cleanup, payload())

    response = client.patch(f"/targets/{created['id']}", json={"api_url": None})
    assert response.status_code == 200
    assert response.json()["api_url"] is None


def test_update_returns_404_for_an_unknown_target(client) -> None:
    response = client.patch(f"/targets/{MISSING_ID}", json={"name": "ghost"})
    assert response.status_code == 404


def test_update_returns_400_for_a_malformed_object_id(client) -> None:
    assert client.patch("/targets/not-an-id", json={"name": "x"}).status_code == 400


def test_update_rejects_invalid_data(client, cleanup, payload) -> None:
    created = _create(client, cleanup, payload())
    response = client.patch(f"/targets/{created['id']}", json={"base_url": "nope"})
    assert response.status_code == 422


def test_update_rejects_changing_created_at(client, cleanup, payload) -> None:
    created = _create(client, cleanup, payload())
    response = client.patch(
        f"/targets/{created['id']}", json={"created_at": "2020-01-01T00:00:00Z"}
    )
    assert response.status_code == 422


def test_update_rejects_a_change_that_would_duplicate_another_target(
    client, cleanup, payload
) -> None:
    first = _create(client, cleanup, payload())
    second = _create(client, cleanup, payload())

    response = client.patch(f"/targets/{second['id']}", json={"name": first["name"]})
    assert response.status_code == 409


# --- delete -----------------------------------------------------------


def test_delete_removes_the_target(client, cleanup, payload) -> None:
    created = _create(client, cleanup, payload())

    response = client.delete(f"/targets/{created['id']}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "id": created["id"]}

    assert client.get(f"/targets/{created['id']}").status_code == 404


def test_delete_returns_404_for_an_unknown_target(client) -> None:
    assert client.delete(f"/targets/{MISSING_ID}").status_code == 404


def test_delete_returns_400_for_a_malformed_object_id(client) -> None:
    assert client.delete("/targets/not-an-id").status_code == 400


# --- persistence ------------------------------------------------------


def test_created_target_is_really_a_document_in_mongodb(
    client, cleanup, payload, settings
) -> None:
    """Prove the data is on the database server, not in process memory.

    This opens its own synchronous driver connection, completely separate
    from the application's async client, and reads the raw document.
    """
    from bson import ObjectId
    from pymongo import MongoClient

    created = _create(client, cleanup, payload())

    with MongoClient(settings.mongodb_uri, tz_aware=True) as direct:
        document = direct[settings.mongodb_database]["targets"].find_one(
            {"_id": ObjectId(created["id"])}
        )

    assert document is not None, "the target was not persisted to MongoDB"
    assert document["name"] == created["name"]
    assert document["base_url"] == "http://localhost:3000"
    assert document["enabled"] is True
    # Stored as a real BSON date, not a string.
    assert hasattr(document["created_at"], "year")
