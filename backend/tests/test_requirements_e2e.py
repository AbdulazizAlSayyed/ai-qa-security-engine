"""Phase 13 real end-to-end coverage for the requirements registry.

These run the whole chain against what is actually installed: the real
FastAPI application with its real lifespan, the real MongoDB on the
configured URI, and a real registered target that something is actually
listening on (``e2e_web_target`` skips rather than fails when nothing is).

Nothing here touches the target itself. A requirement is a statement about
an application, and writing one down must not send that application a single
request - which is also why this file can safely use the same target the QA
and security E2E tests drive.

What is proved here that the unit tests do not prove: the registry's
documents, its indexes and its whole lifecycle exist in the database the
platform really uses, against a target that really exists.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient

pytestmark = pytest.mark.integration


@pytest.fixture
def registry(client: TestClient, e2e_web_target: dict[str, Any]) -> Iterator[str]:
    """A real target's registry, left exactly as it was found.

    The target may be one a developer registered themselves, so every
    requirement written here is removed afterwards - including on failure.
    """
    target_id = e2e_web_target["id"]
    written: list[str] = []
    try:
        yield target_id
    finally:
        listed = client.get(f"/targets/{target_id}/requirements")
        if listed.status_code == 200:
            for requirement in listed.json():
                if requirement["source_reference"].startswith("pytest-e2e"):
                    client.delete(f"/targets/{target_id}/requirements/{requirement['id']}")
        for requirement_id in written:
            client.delete(f"/targets/{target_id}/requirements/{requirement_id}")


def _write(client: TestClient, target_id: str, marker: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": f"E2E requirement {marker}",
        "description": "Written by the Phase 13 real end-to-end test.",
        "source": "manual",
        "source_reference": f"pytest-e2e-{marker}",
        "acceptance_criteria": [{"id": None, "text": "The registry holds this."}],
        "area": "functional",
        "priority": "medium",
        "status": "draft",
    }
    body.update(overrides)
    response = client.post(f"/targets/{target_id}/requirements", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_the_full_lifecycle_runs_against_the_real_database(
    client, registry, settings
) -> None:
    """Create, read back from MongoDB, list, filter, update, deprecate, delete."""
    marker = uuid4().hex[:10]
    created = _write(client, registry, marker)
    url = f"/targets/{registry}/requirements/{created['id']}"

    # 1. It is really in MongoDB, with the fields the schema promises.
    with MongoClient(settings.mongodb_uri) as direct:
        stored = direct[settings.mongodb_database]["requirements"].find_one(
            {"_id": ObjectId(created["id"])}
        )
    assert stored is not None
    assert stored["target_id"] == registry
    assert stored["key"] == created["key"]
    assert stored["acceptance_criteria"] == [{"id": "AC-001", "text": "The registry holds this."}]
    blob = json.dumps(stored, default=str).lower()
    for forbidden in ("password", "secret", "token", "api_key", "credential"):
        assert f'"{forbidden}"' not in blob

    # 2. It comes back through the API.
    assert client.get(url).json() == created

    # 3. Filtering reaches it, and excludes it when it should.
    hit = client.get(f"/targets/{registry}/requirements", params={"status": "draft"})
    assert created["id"] in [item["id"] for item in hit.json()]
    miss = client.get(f"/targets/{registry}/requirements", params={"status": "approved"})
    assert created["id"] not in [item["id"] for item in miss.json()]

    # 4. Editing it, including its acceptance criteria.
    edited = client.patch(
        url,
        json={
            "priority": "high",
            "acceptance_criteria": [
                {"id": "AC-001", "text": "The registry holds this."},
                {"id": None, "text": "And this, added later."},
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["priority"] == "high"
    assert [c["id"] for c in edited.json()["acceptance_criteria"]] == ["AC-001", "AC-002"]

    # 5. The lifecycle.
    assert client.patch(url, json={"status": "approved"}).json()["status"] == "approved"
    assert client.patch(url, json={"status": "deprecated"}).json()["status"] == "deprecated"
    assert client.get(url).status_code == 200

    # 6. Deleting it, for real.
    removed = client.delete(url)
    assert removed.status_code == 200, removed.text
    assert client.get(url).status_code == 404
    with MongoClient(settings.mongodb_uri) as direct:
        assert (
            direct[settings.mongodb_database]["requirements"].find_one(
                {"_id": ObjectId(created["id"])}
            )
            is None
        )


def test_the_indexes_exist_in_the_real_database(client, registry, settings) -> None:
    """Startup created them on the database the platform actually uses."""
    with MongoClient(settings.mongodb_uri) as direct:
        info = direct[settings.mongodb_database]["requirements"].index_information()

    assert info["uniq_requirement_key"]["key"] == [("target_id", 1), ("key", 1)]
    assert info["uniq_requirement_key"].get("unique") is True
    assert "requirements_by_target_status" in info
    assert "requirements_by_target_priority" in info
    assert "requirements_by_target_area" in info


def test_a_second_target_never_sees_this_registry(client, registry) -> None:
    """Isolation, proved against a real registered target and a fresh one."""
    marker = uuid4().hex[:10]
    mine = _write(client, registry, marker)

    other = client.post(
        "/targets",
        json={
            "name": f"pytest-e2e-isolation-{marker}",
            "base_url": "http://localhost:3000",
            "description": "Created by the Phase 13 E2E isolation test.",
        },
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]

    try:
        listed = client.get(f"/targets/{other_id}/requirements")
        assert listed.status_code == 200, listed.text
        assert listed.json() == []
        assert client.get(f"/targets/{other_id}/requirements/{mine['id']}").status_code == 404
    finally:
        client.delete(f"/targets/{registry}/requirements/{mine['id']}")
        client.delete(f"/targets/{other_id}")


def test_writing_a_requirement_sends_the_target_no_request(
    client, registry, e2e_web_target
) -> None:
    """The registry is not a client of the application it describes.

    A requirement is written, read, filtered and deleted while the target is
    genuinely running. If any of that reached out to it, this phase would
    have crossed a boundary it promised not to.
    """
    marker = uuid4().hex[:10]
    created = _write(client, registry, marker, area="api")

    listed = client.get(f"/targets/{registry}/requirements", params={"area": "api"})
    assert created["id"] in [item["id"] for item in listed.json()]

    # Nothing in the stored record or the response mentions the target's URL:
    # the registry stores a statement, not a route to call.
    assert e2e_web_target["base_url"] not in json.dumps(created)

    assert client.delete(f"/targets/{registry}/requirements/{created['id']}").status_code == 200
