"""Phase 13 requirements registry tests.

Three properties carry most of the weight here, and most of this file exists
to hold them down:

**The registry owns the keys.** ``REQ-NNN`` is allocated per target, in
order, and never by a caller. A deleted key is retired rather than reissued,
so a reference written in a ticket keeps meaning the same statement.

**A requirement belongs to exactly one target.** Every route names a target,
the service queries on both halves, and a requirement addressed through the
wrong target is not found rather than returned.

**A requirement is a statement, not a secret.** There is no field a
credential could go into, free text that looks like one is refused, and the
raw MongoDB documents are inspected directly rather than the API's view of
them.

These are integration tests: they talk to the real MongoDB on the configured
URI, because an index that only exists in a mock proves nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

pytestmark = pytest.mark.integration

MISSING_ID = "0" * 24
MALFORMED_ID = "not-an-object-id"

#: The value the tests try to smuggle in. It must never appear anywhere.
SECRET = "hunter2-must-never-be-stored"


@pytest.fixture
def target_cleanup(client: TestClient) -> Iterator[list[str]]:
    """Delete requirements first, then targets - the registry refuses otherwise."""
    created: list[str] = []
    try:
        yield created
    finally:
        for target_id in created:
            listed = client.get(f"/targets/{target_id}/requirements")
            if listed.status_code == 200:
                for requirement in listed.json():
                    client.delete(f"/targets/{target_id}/requirements/{requirement['id']}")
            client.delete(f"/targets/{target_id}")


@pytest.fixture
def make_target(
    client: TestClient, target_cleanup: list[str]
) -> Callable[..., dict[str, Any]]:
    def _make(**overrides: Any) -> dict[str, Any]:
        body = {
            "name": f"pytest-requirements-{uuid4().hex[:10]}",
            "base_url": "http://localhost:3000",
            "description": "Created by the Phase 13 requirements tests.",
        }
        body.update(overrides)
        response = client.post("/targets", json=body)
        assert response.status_code == 201, response.text
        created = response.json()
        target_cleanup.append(created["id"])
        return created

    return _make


@pytest.fixture
def requirement_payload() -> Callable[..., dict[str, Any]]:
    def _build(**overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": f"pytest requirement {uuid4().hex[:8]}",
            "description": "The application must do the thing the document says.",
            "source": "manual",
            "source_reference": "pytest",
            "acceptance_criteria": [],
            "area": "functional",
            "priority": "medium",
            "status": "draft",
        }
        body.update(overrides)
        return body

    return _build


def _create(client: TestClient, target_id: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"/targets/{target_id}/requirements", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- key allocation ---------------------------------------------------------


def test_the_first_requirement_of_a_target_is_req_001(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    created = _create(client, target["id"], requirement_payload())
    assert created["key"] == "REQ-001"
    assert created["key_number"] == 1


def test_keys_are_allocated_in_order(client, make_target, requirement_payload) -> None:
    target = make_target()
    keys = [_create(client, target["id"], requirement_payload())["key"] for _ in range(3)]
    assert keys == ["REQ-001", "REQ-002", "REQ-003"]


def test_numbering_is_scoped_to_one_target(
    client, make_target, requirement_payload
) -> None:
    """Two targets both start at REQ-001; that is not a collision."""
    first, second = make_target(), make_target()
    a = _create(client, first["id"], requirement_payload())
    b = _create(client, second["id"], requirement_payload())

    assert a["key"] == b["key"] == "REQ-001"
    assert a["target_id"] != b["target_id"]
    assert a["id"] != b["id"]


def test_a_gap_in_the_middle_of_the_series_is_never_filled(
    client, make_target, requirement_payload
) -> None:
    """Allocation is the maximum, not the count, so REQ-002 is not handed out twice."""
    target = make_target()
    _create(client, target["id"], requirement_payload())
    second = _create(client, target["id"], requirement_payload())
    _create(client, target["id"], requirement_payload())
    assert second["key"] == "REQ-002"

    removed = client.delete(f"/targets/{target['id']}/requirements/{second['id']}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["key"] == "REQ-002"

    replacement = _create(client, target["id"], requirement_payload())
    assert replacement["key"] == "REQ-004"


def test_deleting_the_highest_requirement_frees_its_number(
    client, make_target, requirement_payload
) -> None:
    """The documented consequence of allocating from the live maximum.

    This is asserted rather than hidden: anything that will later refer to a
    REQ key needs to know that deleting the top of the series can hand that
    number to a different statement. Deprecating instead of deleting keeps
    the key.
    """
    target = make_target()
    _create(client, target["id"], requirement_payload())
    top = _create(client, target["id"], requirement_payload())
    assert top["key"] == "REQ-002"

    assert (
        client.delete(f"/targets/{target['id']}/requirements/{top['id']}").status_code
        == 200
    )

    replacement = _create(client, target["id"], requirement_payload())
    assert replacement["key"] == "REQ-002"
    assert replacement["id"] != top["id"]


def test_the_client_cannot_choose_its_own_key(
    client, make_target, requirement_payload
) -> None:
    """``extra="forbid"`` makes an attempt a 422 rather than a silent no-op."""
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/requirements",
        json=requirement_payload(key="REQ-999"),
    )
    assert response.status_code == 422, response.text


def test_the_unique_key_index_makes_a_duplicate_impossible(
    client, make_target, requirement_payload, settings
) -> None:
    """Proved against the database, not against the service that avoids it."""
    target = make_target()
    created = _create(client, target["id"], requirement_payload())

    with MongoClient(settings.mongodb_uri) as direct:
        collection = direct[settings.mongodb_database]["requirements"]
        stored = collection.find_one({"_id": ObjectId(created["id"])})
        assert stored is not None
        clone = {key: value for key, value in stored.items() if key != "_id"}
        with pytest.raises(DuplicateKeyError):
            collection.insert_one(clone)


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", "   "),
        ("description", ""),
        ("description", "\n\t "),
        ("source", "spreadsheet"),
        ("priority", "p1"),
        ("priority", "must_have"),
        ("status", "tested"),
        ("area", "checkout"),
    ],
)
def test_meaningless_values_are_refused(
    client, make_target, requirement_payload, field, value
) -> None:
    """Whitespace-only text is empty text, and the vocabularies are closed.

    ``status="tested"`` is in this list on purpose: a requirement is never
    tested by this phase, so there is no such state to record.
    """
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/requirements",
        json=requirement_payload(**{field: value}),
    )
    assert response.status_code == 422, response.text


def test_an_empty_acceptance_criterion_is_refused(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/requirements",
        json=requirement_payload(acceptance_criteria=[{"id": None, "text": "   "}]),
    )
    assert response.status_code == 422, response.text


def test_a_malformed_criterion_id_is_refused(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/requirements",
        json=requirement_payload(
            acceptance_criteria=[{"id": "criterion-one", "text": "It works."}]
        ),
    )
    assert response.status_code == 422, response.text


def test_a_malformed_target_id_is_a_400(client, requirement_payload) -> None:
    response = client.post(
        f"/targets/{MALFORMED_ID}/requirements", json=requirement_payload()
    )
    assert response.status_code == 400, response.text


def test_an_unknown_target_is_a_404(client, requirement_payload) -> None:
    response = client.post(
        f"/targets/{MISSING_ID}/requirements", json=requirement_payload()
    )
    assert response.status_code == 404, response.text


def test_a_malformed_requirement_id_is_a_400(client, make_target) -> None:
    target = make_target()
    response = client.get(f"/targets/{target['id']}/requirements/{MALFORMED_ID}")
    assert response.status_code == 400, response.text


def test_an_unknown_requirement_is_a_404(client, make_target) -> None:
    target = make_target()
    response = client.get(f"/targets/{target['id']}/requirements/{MISSING_ID}")
    assert response.status_code == 404, response.text


# --- target isolation -------------------------------------------------------


def test_one_targets_registry_never_shows_anothers(
    client, make_target, requirement_payload
) -> None:
    first, second = make_target(), make_target()
    mine = _create(client, first["id"], requirement_payload(title="only on the first"))
    _create(client, second["id"], requirement_payload(title="only on the second"))

    listed = client.get(f"/targets/{first['id']}/requirements")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [mine["id"]]


def test_a_requirement_is_not_found_through_another_target(
    client, make_target, requirement_payload
) -> None:
    first, second = make_target(), make_target()
    mine = _create(client, first["id"], requirement_payload())

    response = client.get(f"/targets/{second['id']}/requirements/{mine['id']}")
    assert response.status_code == 404, response.text


def test_another_targets_requirement_cannot_be_updated(
    client, make_target, requirement_payload
) -> None:
    first, second = make_target(), make_target()
    mine = _create(client, first["id"], requirement_payload())

    response = client.patch(
        f"/targets/{second['id']}/requirements/{mine['id']}", json={"title": "hijacked"}
    )
    assert response.status_code == 404, response.text

    unchanged = client.get(f"/targets/{first['id']}/requirements/{mine['id']}").json()
    assert unchanged["title"] == mine["title"]


def test_another_targets_requirement_cannot_be_deleted(
    client, make_target, requirement_payload
) -> None:
    first, second = make_target(), make_target()
    mine = _create(client, first["id"], requirement_payload())

    response = client.delete(f"/targets/{second['id']}/requirements/{mine['id']}")
    assert response.status_code == 404, response.text
    assert client.get(f"/targets/{first['id']}/requirements/{mine['id']}").status_code == 200


def test_a_requirement_cannot_be_moved_to_another_target(
    client, make_target, requirement_payload
) -> None:
    """There is no ``target_id`` field on the patch, so the attempt is a 422."""
    first, second = make_target(), make_target()
    mine = _create(client, first["id"], requirement_payload())

    response = client.patch(
        f"/targets/{first['id']}/requirements/{mine['id']}",
        json={"target_id": second["id"]},
    )
    assert response.status_code == 422, response.text


def test_a_target_with_requirements_is_not_deleted_silently(
    client, make_target, requirement_payload
) -> None:
    """Cascading would delete statements someone wrote without saying so."""
    target = make_target()
    _create(client, target["id"], requirement_payload())

    response = client.delete(f"/targets/{target['id']}")
    assert response.status_code == 409, response.text
    assert "requirement" in response.json()["detail"].lower()
    assert client.get(f"/targets/{target['id']}").status_code == 200


# --- CRUD, filtering and lifecycle ------------------------------------------


def test_a_requirement_reads_back_as_it_was_written(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    body = requirement_payload(
        title="Checkout rejects an order that exceeds available stock",
        description="The system must reject an order whose quantity exceeds stock.",
        source="user_story",
        source_reference="STORY-118",
        area="functional",
        priority="high",
        acceptance_criteria=[
            {"id": None, "text": "Quantity equal to stock is accepted."},
            {"id": None, "text": "Quantity greater than stock is rejected."},
        ],
    )
    created = _create(client, target["id"], body)
    fetched = client.get(f"/targets/{target['id']}/requirements/{created['id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == created

    assert created["source"] == "user_story"
    assert created["source_reference"] == "STORY-118"
    assert created["priority"] == "high"
    assert [c["id"] for c in created["acceptance_criteria"]] == ["AC-001", "AC-002"]


def test_the_registry_lists_in_req_order(client, make_target, requirement_payload) -> None:
    target = make_target()
    for _ in range(3):
        _create(client, target["id"], requirement_payload())
    listed = client.get(f"/targets/{target['id']}/requirements").json()
    assert [item["key"] for item in listed] == ["REQ-001", "REQ-002", "REQ-003"]


@pytest.mark.parametrize(
    ("filter_name", "kept", "dropped"),
    [
        ("status", "approved", "draft"),
        ("priority", "critical", "low"),
        ("area", "security", "functional"),
        ("source", "brd", "manual"),
    ],
)
def test_each_filter_narrows_the_registry(
    client, make_target, requirement_payload, filter_name, kept, dropped
) -> None:
    target = make_target()
    wanted = _create(client, target["id"], requirement_payload(**{filter_name: kept}))
    _create(client, target["id"], requirement_payload(**{filter_name: dropped}))

    response = client.get(
        f"/targets/{target['id']}/requirements", params={filter_name: kept}
    )
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [wanted["id"]]


def test_an_unknown_filter_value_is_refused(client, make_target) -> None:
    target = make_target()
    response = client.get(
        f"/targets/{target['id']}/requirements", params={"status": "tested"}
    )
    assert response.status_code == 422, response.text


def test_a_new_requirement_is_a_draft(client, make_target, requirement_payload) -> None:
    target = make_target()
    body = requirement_payload()
    body.pop("status")
    body.pop("priority")
    body.pop("area")
    created = _create(client, target["id"], body)
    assert created["status"] == "draft"
    assert created["priority"] == "medium"
    assert created["area"] == "functional"


def test_the_lifecycle_runs_draft_approved_deprecated(
    client, make_target, requirement_payload
) -> None:
    """Deprecating keeps the record; only an explicit delete removes it."""
    target = make_target()
    created = _create(client, target["id"], requirement_payload())
    url = f"/targets/{target['id']}/requirements/{created['id']}"

    approved = client.patch(url, json={"status": "approved"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    # An approved requirement stays editable - nothing here freezes it.
    edited = client.patch(url, json={"title": "reworded after approval"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "reworded after approval"

    deprecated = client.patch(url, json={"status": "deprecated"})
    assert deprecated.status_code == 200, deprecated.text
    assert deprecated.json()["status"] == "deprecated"
    assert client.get(url).status_code == 200


def test_an_empty_patch_changes_nothing(client, make_target, requirement_payload) -> None:
    target = make_target()
    created = _create(client, target["id"], requirement_payload())
    response = client.patch(
        f"/targets/{target['id']}/requirements/{created['id']}", json={}
    )
    assert response.status_code == 200, response.text
    assert response.json() == created


# --- acceptance criteria ----------------------------------------------------


def test_criteria_are_numbered_from_ac_001(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    created = _create(
        client,
        target["id"],
        requirement_payload(
            acceptance_criteria=[
                {"id": None, "text": "First."},
                {"id": None, "text": "Second."},
                {"text": "Third, with the id left out entirely."},
            ]
        ),
    )
    assert [c["id"] for c in created["acceptance_criteria"]] == [
        "AC-001",
        "AC-002",
        "AC-003",
    ]


def test_an_echoed_criterion_id_keeps_its_criterion(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    created = _create(
        client,
        target["id"],
        requirement_payload(
            acceptance_criteria=[
                {"id": None, "text": "Quantity equal to stock is accepted."},
                {"id": None, "text": "Quantity greater than stock is rejected."},
            ]
        ),
    )
    url = f"/targets/{target['id']}/requirements/{created['id']}"

    edited = client.patch(
        url,
        json={
            "acceptance_criteria": [
                {"id": "AC-001", "text": "Quantity equal to stock is accepted (reworded)."},
                {"id": "AC-002", "text": "Quantity greater than stock is rejected."},
                {"id": None, "text": "Stock is not reduced for a rejected order."},
            ]
        },
    )
    assert edited.status_code == 200, edited.text
    criteria = edited.json()["acceptance_criteria"]
    assert [c["id"] for c in criteria] == ["AC-001", "AC-002", "AC-003"]
    assert criteria[0]["text"].endswith("(reworded).")


def test_a_removed_criterion_number_is_not_reused(
    client, make_target, requirement_payload
) -> None:
    """AC-002 must never come back meaning a different statement."""
    target = make_target()
    created = _create(
        client,
        target["id"],
        requirement_payload(
            acceptance_criteria=[
                {"id": None, "text": "First."},
                {"id": None, "text": "Second."},
            ]
        ),
    )
    url = f"/targets/{target['id']}/requirements/{created['id']}"

    dropped = client.patch(
        url, json={"acceptance_criteria": [{"id": "AC-001", "text": "First."}]}
    )
    assert dropped.status_code == 200, dropped.text
    assert [c["id"] for c in dropped.json()["acceptance_criteria"]] == ["AC-001"]

    added = client.patch(
        url,
        json={
            "acceptance_criteria": [
                {"id": "AC-001", "text": "First."},
                {"id": None, "text": "Something else entirely."},
            ]
        },
    )
    assert added.status_code == 200, added.text
    assert [c["id"] for c in added.json()["acceptance_criteria"]] == ["AC-001", "AC-003"]


def test_reordering_criteria_keeps_their_ids(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    created = _create(
        client,
        target["id"],
        requirement_payload(
            acceptance_criteria=[
                {"id": None, "text": "First."},
                {"id": None, "text": "Second."},
            ]
        ),
    )
    url = f"/targets/{target['id']}/requirements/{created['id']}"

    swapped = client.patch(
        url,
        json={
            "acceptance_criteria": [
                {"id": "AC-002", "text": "Second."},
                {"id": "AC-001", "text": "First."},
            ]
        },
    )
    assert swapped.status_code == 200, swapped.text
    criteria = swapped.json()["acceptance_criteria"]
    assert [(c["id"], c["text"]) for c in criteria] == [
        ("AC-002", "Second."),
        ("AC-001", "First."),
    ]


def test_an_invented_criterion_id_is_replaced_not_honoured(
    client, make_target, requirement_payload
) -> None:
    """A client cannot claim AC-042 on a requirement that never had one."""
    target = make_target()
    created = _create(client, target["id"], requirement_payload())
    url = f"/targets/{target['id']}/requirements/{created['id']}"

    response = client.patch(
        url, json={"acceptance_criteria": [{"id": "AC-042", "text": "Invented."}]}
    )
    assert response.status_code == 200, response.text
    assert [c["id"] for c in response.json()["acceptance_criteria"]] == ["AC-001"]


# --- MongoDB and secret handling --------------------------------------------


def test_the_requirements_collection_has_its_indexes(
    client, make_target, requirement_payload, settings
) -> None:
    """Startup creates them; this reads what MongoDB actually holds."""
    target = make_target()
    _create(client, target["id"], requirement_payload())

    with MongoClient(settings.mongodb_uri) as direct:
        info = direct[settings.mongodb_database]["requirements"].index_information()

    assert "uniq_requirement_key" in info
    assert info["uniq_requirement_key"].get("unique") is True
    assert info["uniq_requirement_key"]["key"] == [("target_id", 1), ("key", 1)]

    for name, keys in (
        ("requirements_by_target_status", [("target_id", 1), ("status", 1)]),
        ("requirements_by_target_priority", [("target_id", 1), ("priority", 1)]),
        ("requirements_by_target_area", [("target_id", 1), ("area", 1)]),
    ):
        assert name in info, f"{name} is missing"
        assert info[name]["key"][: len(keys)] == keys


def test_the_stored_document_holds_exactly_what_it_should(
    client, make_target, requirement_payload, settings
) -> None:
    """Read the raw document, not the API's view of it."""
    target = make_target()
    created = _create(
        client,
        target["id"],
        requirement_payload(acceptance_criteria=[{"id": None, "text": "It holds."}]),
    )

    with MongoClient(settings.mongodb_uri) as direct:
        document = direct[settings.mongodb_database]["requirements"].find_one(
            {"_id": ObjectId(created["id"])}
        )

    assert document is not None
    assert set(document) == {
        "_id",
        "target_id",
        "key",
        "key_number",
        "title",
        "description",
        "source",
        "source_reference",
        "acceptance_criteria",
        "criteria_sequence",
        "area",
        "priority",
        "status",
        "extraction_id",
        "created_at",
        "updated_at",
    }
    assert document["target_id"] == target["id"]
    assert document["key"] == "REQ-001"
    assert document["acceptance_criteria"] == [{"id": "AC-001", "text": "It holds."}]


def test_internal_bookkeeping_stays_out_of_the_api(
    client, make_target, requirement_payload
) -> None:
    """``criteria_sequence`` is how ids are allocated; it is not a requirement's business."""
    target = make_target()
    created = _create(client, target["id"], requirement_payload())
    assert "criteria_sequence" not in created
    listed = client.get(f"/targets/{target['id']}/requirements").json()
    assert all("criteria_sequence" not in item for item in listed)


@pytest.mark.parametrize(
    "field",
    ["title", "description", "source_reference"],
)
def test_text_that_looks_like_a_credential_is_refused(
    client, make_target, requirement_payload, field
) -> None:
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/requirements",
        json=requirement_payload(**{field: f"admin password={SECRET}"}),
    )
    assert response.status_code == 422, response.text
    assert SECRET not in response.text


def test_a_credential_in_an_acceptance_criterion_is_refused(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/requirements",
        json=requirement_payload(
            acceptance_criteria=[{"id": None, "text": f"log in with secret={SECRET}"}]
        ),
    )
    assert response.status_code == 422, response.text
    assert SECRET not in response.text


def test_a_requirement_has_no_field_a_credential_could_go_in(
    client, make_target, requirement_payload
) -> None:
    target = make_target()
    for forbidden in ("password", "secret", "token", "api_key", "credential"):
        response = client.post(
            f"/targets/{target['id']}/requirements",
            json=requirement_payload(**{forbidden: SECRET}),
        )
        assert response.status_code == 422, f"{forbidden}: {response.text}"
        assert SECRET not in response.text


def test_no_secret_shaped_value_reaches_mongodb(
    client, make_target, requirement_payload, settings
) -> None:
    target = make_target()
    created = _create(client, target["id"], requirement_payload())

    with MongoClient(settings.mongodb_uri) as direct:
        document = direct[settings.mongodb_database]["requirements"].find_one(
            {"_id": ObjectId(created["id"])}
        )

    blob = json.dumps(document, default=str).lower()
    assert SECRET not in blob
    for forbidden in ("password", "secret", "token", "cookie", "api_key"):
        assert f'"{forbidden}"' not in blob
