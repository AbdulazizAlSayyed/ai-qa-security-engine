"""Phase 12 test account tests.

Two properties are worth more than the rest of this file, and most of it
exists to hold them down:

**No secret is accepted, stored or returned.** There is no field a password
could go into, ``credential_reference`` only accepts an environment variable
*name*, and the raw MongoDB documents are inspected directly to prove nothing
secret-shaped reached the database.

**An account belongs to exactly one target.** Every route names a target, the
service queries on both halves, and an account addressed through the wrong
target is not found rather than returned.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

pytestmark = pytest.mark.integration

MISSING_ID = "0" * 24

#: The value the tests try to smuggle in. It must never appear anywhere.
SECRET = "hunter2-must-never-be-stored"


@pytest.fixture
def target_cleanup(client: TestClient) -> Iterator[list[str]]:
    """Delete accounts first, then targets - the registry refuses otherwise.

    A target a test already deleted answers 404 here, which is fine: there is
    then nothing left to clean up for it.
    """
    created: list[str] = []
    try:
        yield created
    finally:
        for target_id in created:
            listed = client.get(f"/targets/{target_id}/test-accounts")
            if listed.status_code == 200:
                for account in listed.json():
                    client.delete(f"/targets/{target_id}/test-accounts/{account['id']}")
            client.delete(f"/targets/{target_id}")


@pytest.fixture
def make_target(client: TestClient, target_cleanup: list[str]) -> Callable[..., dict[str, Any]]:
    def _make(**overrides: Any) -> dict[str, Any]:
        body = {
            "name": f"pytest-accounts-{uuid4().hex[:10]}",
            "base_url": "http://localhost:3000",
            "description": "Created by the Phase 12 account tests.",
        }
        body.update(overrides)
        response = client.post("/targets", json=body)
        assert response.status_code == 201, response.text
        created = response.json()
        target_cleanup.append(created["id"])
        return created

    return _make


@pytest.fixture
def account_payload() -> Callable[..., dict[str, Any]]:
    def _build(**overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": f"pytest-account-{uuid4().hex[:8]}",
            "role": "admin",
            "purpose": "authorization_test_user",
            "username": "admin@test.local",
            "credential_reference": "E2E_ADMIN_PASSWORD",
            "description": "Created by the automated test suite.",
            "enabled": True,
        }
        body.update(overrides)
        return body

    return _build


def _create(
    client: TestClient, target_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(f"/targets/{target_id}/test-accounts", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- CRUD -------------------------------------------------------------


def test_create_returns_201_and_safe_metadata(client, make_target, account_payload) -> None:
    target = make_target()
    body = account_payload()
    created = _create(client, target["id"], body)

    assert len(created["id"]) == 24
    assert created["target_id"] == target["id"]
    assert created["name"] == body["name"]
    assert created["role"] == "admin"
    assert created["purpose"] == "authorization_test_user"
    assert created["username"] == "admin@test.local"
    assert created["credential_reference"] == "E2E_ADMIN_PASSWORD"
    assert created["enabled"] is True
    assert "credential_available" in created


def test_listing_returns_only_this_targets_accounts(client, make_target, account_payload) -> None:
    first, second = make_target(), make_target()
    mine = _create(client, first["id"], account_payload())
    theirs = _create(client, second["id"], account_payload())

    listed = client.get(f"/targets/{first['id']}/test-accounts").json()
    ids = {account["id"] for account in listed}
    assert mine["id"] in ids
    assert theirs["id"] not in ids


def test_get_update_and_disable(client, make_target, account_payload) -> None:
    target = make_target()
    created = _create(client, target["id"], account_payload())

    fetched = client.get(f"/targets/{target['id']}/test-accounts/{created['id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == created["id"]

    updated = client.patch(
        f"/targets/{target['id']}/test-accounts/{created['id']}",
        json={"purpose": "primary_test_user", "role": "user"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["purpose"] == "primary_test_user"
    assert updated.json()["role"] == "user"
    assert updated.json()["id"] == created["id"]

    disabled = client.patch(
        f"/targets/{target['id']}/test-accounts/{created['id']}", json={"enabled": False}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    # Disabling keeps the record: it is not a delete by another name.
    assert client.get(f"/targets/{target['id']}/test-accounts/{created['id']}").status_code == 200


def test_delete_removes_only_that_account(client, make_target, account_payload) -> None:
    target = make_target()
    kept = _create(client, target["id"], account_payload())
    doomed = _create(client, target["id"], account_payload())

    response = client.delete(f"/targets/{target['id']}/test-accounts/{doomed['id']}")
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True, "id": doomed["id"]}

    assert client.get(f"/targets/{target['id']}/test-accounts/{doomed['id']}").status_code == 404
    assert client.get(f"/targets/{target['id']}/test-accounts/{kept['id']}").status_code == 200


def test_a_duplicate_name_on_one_target_is_rejected(client, make_target, account_payload) -> None:
    target = make_target()
    body = account_payload()
    _create(client, target["id"], body)
    assert client.post(f"/targets/{target['id']}/test-accounts", json=body).status_code == 409


def test_the_same_name_on_two_targets_is_fine(client, make_target, account_payload) -> None:
    first, second = make_target(), make_target()
    body = account_payload()
    _create(client, first["id"], body)
    assert client.post(f"/targets/{second['id']}/test-accounts", json=body).status_code == 201


# --- the account belongs to one target --------------------------------


def test_an_account_cannot_be_reached_through_another_target(
    client, make_target, account_payload
) -> None:
    """The nesting in the URL is a boundary, not decoration."""
    owner, other = make_target(), make_target()
    account = _create(client, owner["id"], account_payload())

    assert client.get(f"/targets/{other['id']}/test-accounts/{account['id']}").status_code == 404
    assert (
        client.patch(
            f"/targets/{other['id']}/test-accounts/{account['id']}",
            json={"enabled": False},
        ).status_code
        == 404
    )
    assert client.delete(f"/targets/{other['id']}/test-accounts/{account['id']}").status_code == 404

    # And the account is untouched by any of that.
    assert client.get(f"/targets/{owner['id']}/test-accounts/{account['id']}").json()["enabled"] is True


def test_an_unknown_target_is_a_404(client, account_payload) -> None:
    assert client.post(f"/targets/{MISSING_ID}/test-accounts", json=account_payload()).status_code == 404
    assert client.get(f"/targets/{MISSING_ID}/test-accounts").status_code == 404


def test_a_malformed_target_id_is_a_400(client, account_payload) -> None:
    assert client.post("/targets/not-an-id/test-accounts", json=account_payload()).status_code == 400
    assert client.get("/targets/not-an-id/test-accounts").status_code == 400


def test_a_malformed_account_id_is_a_400(client, make_target) -> None:
    target = make_target()
    assert client.get(f"/targets/{target['id']}/test-accounts/not-an-id").status_code == 400


def test_target_id_cannot_be_set_through_the_body(client, make_target, account_payload) -> None:
    """The target comes from the path. Sending one in the body is a 422."""
    owner, other = make_target(), make_target()
    response = client.post(
        f"/targets/{owner['id']}/test-accounts",
        json=account_payload(target_id=other["id"]),
    )
    assert response.status_code == 422, response.text


def test_target_id_cannot_be_moved_by_an_update(client, make_target, account_payload) -> None:
    owner, other = make_target(), make_target()
    account = _create(client, owner["id"], account_payload())
    response = client.patch(
        f"/targets/{owner['id']}/test-accounts/{account['id']}",
        json={"target_id": other["id"]},
    )
    assert response.status_code == 422, response.text


def test_a_target_with_accounts_is_not_deleted_silently(
    client, make_target, account_payload
) -> None:
    """Deleting a target would orphan or destroy identities. Neither happens quietly."""
    target = make_target()
    account = _create(client, target["id"], account_payload())

    response = client.delete(f"/targets/{target['id']}")
    assert response.status_code == 409, response.text
    assert "test account" in response.text

    # Both survive.
    assert client.get(f"/targets/{target['id']}").status_code == 200
    assert client.get(f"/targets/{target['id']}/test-accounts/{account['id']}").status_code == 200

    # And once the account is gone, the target deletes normally.
    client.delete(f"/targets/{target['id']}/test-accounts/{account['id']}")
    assert client.delete(f"/targets/{target['id']}").status_code == 200


# --- roles and purposes -----------------------------------------------


@pytest.mark.parametrize("role", ["admin", "user", "readonly", "anonymous", "custom"])
def test_every_supported_role_is_accepted(client, make_target, account_payload, role) -> None:
    target = make_target()
    body = account_payload(role=role)
    if role == "anonymous":
        body["username"] = None
        body["credential_reference"] = None
    assert _create(client, target["id"], body)["role"] == role


@pytest.mark.parametrize("role", ["superuser", "ADMIN", "root", ""])
def test_an_unsupported_role_is_rejected(client, make_target, account_payload, role) -> None:
    target = make_target()
    assert (
        client.post(f"/targets/{target['id']}/test-accounts", json=account_payload(role=role)).status_code
        == 422
    )


def test_an_anonymous_account_carries_no_identity(client, make_target, account_payload) -> None:
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/test-accounts",
        json=account_payload(role="anonymous", username="someone@test.local"),
    )
    assert response.status_code == 422, response.text
    assert "anonymous" in response.text


def test_purpose_is_free_text_within_a_length_limit(client, make_target, account_payload) -> None:
    target = make_target()
    assert _create(client, target["id"], account_payload(purpose="whatever we call it"))[
        "purpose"
    ] == "whatever we call it"
    assert (
        client.post(
            f"/targets/{target['id']}/test-accounts", json=account_payload(purpose="x" * 500)
        ).status_code
        == 422
    )


# --- secrets ----------------------------------------------------------


@pytest.mark.parametrize("field", ["password", "secret", "token", "cookie", "credential"])
def test_a_secret_field_is_refused_outright(client, make_target, account_payload, field) -> None:
    """There is no field to put a credential in, and adding one is a 422."""
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/test-accounts", json=account_payload(**{field: SECRET})
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field", ["password", "secret", "token", "cookie", "credential"])
def test_a_rejected_credential_is_not_echoed_back(
    client, make_target, account_payload, field
) -> None:
    """Refusing the value is not enough: the error must not quote it either.

    FastAPI's default 422 includes the offending input so a caller can see
    what was wrong with it, which would print the password straight back
    into the response body.
    """
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/test-accounts", json=account_payload(**{field: SECRET})
    )
    assert response.status_code == 422
    assert SECRET not in response.text, "the rejected credential was echoed back"
    assert "<redacted>" in response.text


def test_a_credential_pasted_into_credential_reference_is_not_echoed(
    client, make_target, account_payload
) -> None:
    """``credential_reference`` is itself a credential-shaped field name."""
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/test-accounts",
        json=account_payload(credential_reference=SECRET),
    )
    assert response.status_code == 422
    assert SECRET not in response.text


def test_ordinary_validation_errors_still_say_what_they_got(
    client, make_target, account_payload
) -> None:
    """Only credential fields are redacted; debuggability is kept elsewhere."""
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/test-accounts", json=account_payload(role="superuser")
    )
    assert response.status_code == 422
    assert "superuser" in response.text


@pytest.mark.parametrize(
    "value",
    [SECRET, "my_password", "lowercase", "E2E ADMIN PASSWORD", "1PASSWORD", "-X-", "p@ssw0rd!"],
)
def test_credential_reference_only_accepts_an_env_var_name(
    client, make_target, account_payload, value
) -> None:
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/test-accounts",
        json=account_payload(credential_reference=value),
    )
    assert response.status_code == 422, response.text
    assert "environment variable" in response.text


@pytest.mark.parametrize("field", ["purpose", "description", "name"])
def test_a_credential_pasted_into_free_text_is_refused(
    client, make_target, account_payload, field
) -> None:
    target = make_target()
    response = client.post(
        f"/targets/{target['id']}/test-accounts",
        json=account_payload(**{field: f"password={SECRET}"}),
    )
    assert response.status_code == 422, response.text
    # And the error does not repeat what was pasted in.
    assert SECRET not in response.text


def test_no_response_ever_contains_a_secret(client, make_target, account_payload) -> None:
    """Sweep every account response for credential-shaped content."""
    target = make_target()
    created = _create(client, target["id"], account_payload())

    responses = [
        client.post(f"/targets/{target['id']}/test-accounts", json=account_payload()),
        client.get(f"/targets/{target['id']}/test-accounts"),
        client.get(f"/targets/{target['id']}/test-accounts/{created['id']}"),
        client.patch(
            f"/targets/{target['id']}/test-accounts/{created['id']}", json={"enabled": False}
        ),
    ]
    for response in responses:
        assert response.status_code in (200, 201), response.text
        body = response.text
        assert SECRET not in body
        # No key that would carry a credential, in any casing.
        for forbidden in ("password", "secret", "token", "cookie"):
            assert not re.search(rf'"{forbidden}"\s*:', body, re.IGNORECASE), (
                f"{forbidden!r} key present in {body[:200]}"
            )
        # The reference is a name, and names are all that is returned.
        payload = response.json()
        for account in payload if isinstance(payload, list) else [payload]:
            assert account.get("credential_reference") in (None, "E2E_ADMIN_PASSWORD")


def test_nothing_secret_shaped_reaches_mongodb(
    client, make_target, account_payload, settings
) -> None:
    """Read the raw document, not the API's view of it."""
    target = make_target()
    created = _create(client, target["id"], account_payload())

    with MongoClient(settings.mongodb_uri) as direct:
        document = direct[settings.mongodb_database]["test_accounts"].find_one(
            {"target_id": target["id"], "name": created["name"]}
        )

    assert document is not None
    assert set(document) == {
        "_id",
        "target_id",
        "name",
        "role",
        "purpose",
        "username",
        "credential_reference",
        "description",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert document["credential_reference"] == "E2E_ADMIN_PASSWORD"

    blob = json.dumps(document, default=str)
    assert SECRET not in blob
    for forbidden in ("password", "secret", "token", "cookie"):
        assert f'"{forbidden}"' not in blob.lower()


def test_credential_availability_reports_presence_and_never_the_value(
    client, make_target, account_payload, monkeypatch
) -> None:
    """The operator needs to know the variable is set, not what it holds."""
    target = make_target()
    monkeypatch.delenv("E2E_ADMIN_PASSWORD", raising=False)
    created = _create(client, target["id"], account_payload())
    assert created["credential_available"] is False

    monkeypatch.setenv("E2E_ADMIN_PASSWORD", SECRET)
    response = client.get(f"/targets/{target['id']}/test-accounts/{created['id']}")
    assert response.json()["credential_available"] is True
    assert SECRET not in response.text


def test_an_account_without_a_reference_reports_no_credential(
    client, make_target, account_payload
) -> None:
    target = make_target()
    created = _create(
        client, target["id"], account_payload(credential_reference=None)
    )
    assert created["credential_reference"] is None
    assert created["credential_available"] is False


# --- real target E2E --------------------------------------------------


@pytest.mark.playwright
def test_the_full_account_lifecycle_against_a_real_target(
    client: TestClient, e2e_web_target, account_payload
) -> None:
    """Create -> retrieve -> update -> disable, on a genuinely running target.

    ``e2e_web_target`` (tests/conftest.py) supplies the target and skips when
    nothing is reachable. This exercises the Phase 12 surface against a real
    registered application rather than a fixture-made one, and sweeps every
    response for credential-shaped content on the way through.

    Nothing here scans, authenticates or sends a state-changing request to
    the target: Phase 12 is configuration, and the target is only read.
    """
    target_id = e2e_web_target["id"]
    body = account_payload(name=f"pytest-e2e-account-{uuid4().hex[:8]}")

    created = client.post(f"/targets/{target_id}/test-accounts", json=body)
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    try:
        fetched = client.get(f"/targets/{target_id}/test-accounts/{account_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["target_id"] == target_id

        updated = client.patch(
            f"/targets/{target_id}/test-accounts/{account_id}",
            json={"purpose": "primary_test_user"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["purpose"] == "primary_test_user"

        disabled = client.patch(
            f"/targets/{target_id}/test-accounts/{account_id}", json={"enabled": False}
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["enabled"] is False

        # The target itself still reads back with a complete profile.
        profile = client.get(f"/targets/{target_id}")
        assert profile.status_code == 200, profile.text
        assert "security_policy" in profile.json()

        for response in (created, fetched, updated, disabled, profile):
            assert SECRET not in response.text
            for forbidden in ("password", "secret", "token", "cookie"):
                assert not re.search(rf'"{forbidden}"\s*:', response.text, re.IGNORECASE)
    finally:
        client.delete(f"/targets/{target_id}/test-accounts/{account_id}")
