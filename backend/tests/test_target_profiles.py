"""Phase 12 target profile tests.

These run against the real MongoDB, like the rest of the target registry
tests, and clean up everything they create.

The centre of gravity here is the fail-closed rule. Every capability defaults
to off, ``authorized_for_testing`` gates the rest, production is treated more
conservatively, and a PATCH is judged on the document it would produce rather
than the fields it mentions - so none of those can be got around one request
at a time.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.models.target import (
    PROFILE_DEFAULTS,
    AuthMethod,
    Environment,
    OwnershipStatus,
    TokenLocation,
    with_profile_defaults,
)

pytestmark = pytest.mark.integration

FORM_AUTH = {
    "enabled": True,
    "method": "form",
    "login_url": "http://localhost:3000/login",
    "username_field": "login-email",
    "password_field": "login-password",
    "token_location": "local_storage",
}


@pytest.fixture
def cleanup(client: TestClient) -> Iterator[list[str]]:
    created: list[str] = []
    try:
        yield created
    finally:
        for target_id in created:
            client.delete(f"/targets/{target_id}")


@pytest.fixture
def payload() -> Callable[..., dict[str, Any]]:
    def _build(**overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": f"pytest-profile-{uuid4().hex[:10]}",
            "base_url": "http://localhost:3000",
            "description": "Created by the Phase 12 test suite.",
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


# --- defaults ---------------------------------------------------------


def test_a_new_target_is_not_authorized_for_anything(client, cleanup, payload) -> None:
    """The whole point of the defaults: registering is not consenting."""
    created = _create(client, cleanup, payload())

    policy = created["security_policy"]
    assert policy == {
        "authorized_for_testing": False,
        "allow_security_scanning": False,
        "allow_authenticated_testing": False,
        "allow_state_changing_requests": False,
    }
    assert created["environment"] == Environment.LOCAL.value
    assert created["ownership_status"] == OwnershipStatus.UNKNOWN.value
    assert created["authentication"]["enabled"] is False
    assert created["authentication"]["method"] == AuthMethod.NONE.value
    assert created["authentication"]["token_location"] == TokenLocation.NONE.value


def test_the_profile_survives_a_round_trip(client, cleanup, payload) -> None:
    created = _create(
        client,
        cleanup,
        payload(
            environment="staging",
            ownership_status="owned",
            authentication=FORM_AUTH,
            security_policy={
                "authorized_for_testing": True,
                "allow_security_scanning": True,
                "allow_authenticated_testing": True,
            },
        ),
    )

    fetched = client.get(f"/targets/{created['id']}").json()
    assert fetched["environment"] == "staging"
    assert fetched["ownership_status"] == "owned"
    assert fetched["authentication"] == FORM_AUTH
    assert fetched["security_policy"]["allow_authenticated_testing"] is True
    assert fetched["security_policy"]["allow_state_changing_requests"] is False


# --- the authorization gate -------------------------------------------


@pytest.mark.parametrize(
    "capability",
    [
        "allow_security_scanning",
        "allow_authenticated_testing",
        "allow_state_changing_requests",
    ],
)
def test_no_capability_may_be_enabled_without_authorization(
    client, payload, capability: str
) -> None:
    response = client.post(
        "/targets", json=payload(security_policy={capability: True})
    )
    assert response.status_code == 422, response.text
    assert "authorized_for_testing" in response.text


def test_authorization_alone_grants_nothing(client, cleanup, payload) -> None:
    """Authorising a target is not the same as enabling anything on it."""
    created = _create(
        client, cleanup, payload(security_policy={"authorized_for_testing": True})
    )
    policy = created["security_policy"]
    assert policy["authorized_for_testing"] is True
    assert not any(
        policy[name]
        for name in (
            "allow_security_scanning",
            "allow_authenticated_testing",
            "allow_state_changing_requests",
        )
    )


def test_withdrawing_authorization_cannot_orphan_a_capability(
    client, cleanup, payload
) -> None:
    """A patch is judged on the document it produces.

    Clearing ``authorized_for_testing`` while scanning stays enabled is two
    individually valid fields adding up to a state the gate exists to
    prevent, so the whole patch is refused.
    """
    created = _create(
        client,
        cleanup,
        payload(
            security_policy={
                "authorized_for_testing": True,
                "allow_security_scanning": True,
            }
        ),
    )

    response = client.patch(
        f"/targets/{created['id']}",
        json={"security_policy": {"authorized_for_testing": False, "allow_security_scanning": True}},
    )
    assert response.status_code == 422, response.text

    # And the stored target is untouched.
    assert client.get(f"/targets/{created['id']}").json()["security_policy"][
        "allow_security_scanning"
    ] is True


def test_authorization_can_be_withdrawn_together_with_its_capabilities(
    client, cleanup, payload
) -> None:
    created = _create(
        client,
        cleanup,
        payload(
            security_policy={
                "authorized_for_testing": True,
                "allow_security_scanning": True,
            }
        ),
    )

    response = client.patch(
        f"/targets/{created['id']}",
        json={"security_policy": {"authorized_for_testing": False}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["security_policy"] == {
        "authorized_for_testing": False,
        "allow_security_scanning": False,
        "allow_authenticated_testing": False,
        "allow_state_changing_requests": False,
    }


# --- production is treated conservatively -----------------------------


@pytest.mark.parametrize(
    "capability", ["allow_security_scanning", "allow_state_changing_requests"]
)
def test_production_refuses_scanning_and_writes(client, payload, capability: str) -> None:
    response = client.post(
        "/targets",
        json=payload(
            environment="production",
            security_policy={"authorized_for_testing": True, capability: True},
        ),
    )
    assert response.status_code == 422, response.text
    assert "production" in response.text


def test_moving_a_target_to_production_refuses_the_capabilities_it_holds(
    client, cleanup, payload
) -> None:
    created = _create(
        client,
        cleanup,
        payload(
            environment="staging",
            security_policy={
                "authorized_for_testing": True,
                "allow_state_changing_requests": True,
            },
        ),
    )

    response = client.patch(
        f"/targets/{created['id']}", json={"environment": "production"}
    )
    assert response.status_code == 422, response.text
    assert "production" in response.text


def test_production_may_still_be_authorized_without_capabilities(
    client, cleanup, payload
) -> None:
    created = _create(
        client,
        cleanup,
        payload(
            environment="production",
            security_policy={"authorized_for_testing": True},
        ),
    )
    assert created["environment"] == "production"
    assert created["security_policy"]["authorized_for_testing"] is True


# --- authentication configuration -------------------------------------


def test_authenticated_testing_requires_configured_authentication(
    client, payload
) -> None:
    response = client.post(
        "/targets",
        json=payload(
            security_policy={
                "authorized_for_testing": True,
                "allow_authenticated_testing": True,
            }
        ),
    )
    assert response.status_code == 422, response.text
    assert "authentication.enabled" in response.text


def test_a_form_login_needs_its_fields(client, payload) -> None:
    response = client.post(
        "/targets", json=payload(authentication={"enabled": True, "method": "form"})
    )
    assert response.status_code == 422, response.text
    for field in ("login_url", "username_field", "password_field"):
        assert field in response.text


def test_disabled_authentication_cannot_name_a_method(client, payload) -> None:
    response = client.post(
        "/targets", json=payload(authentication={"enabled": False, "method": "form"})
    )
    assert response.status_code == 422, response.text


def test_enabled_authentication_needs_a_method(client, payload) -> None:
    response = client.post(
        "/targets", json=payload(authentication={"enabled": True, "method": "none"})
    )
    assert response.status_code == 422, response.text


def test_a_bearer_profile_needs_no_form_fields(client, cleanup, payload) -> None:
    created = _create(
        client,
        cleanup,
        payload(authentication={"enabled": True, "method": "bearer", "token_location": "header"}),
    )
    assert created["authentication"]["method"] == "bearer"
    assert created["authentication"]["login_url"] is None


# --- vocabularies and URLs --------------------------------------------


@pytest.mark.parametrize("environment", ["prod", "PRODUCTION", "", "qa"])
def test_unsupported_environment_is_rejected(client, payload, environment: str) -> None:
    assert client.post("/targets", json=payload(environment=environment)).status_code == 422


@pytest.mark.parametrize("value", ["owner", "mine", ""])
def test_unsupported_ownership_status_is_rejected(client, payload, value: str) -> None:
    assert client.post("/targets", json=payload(ownership_status=value)).status_code == 422


@pytest.mark.parametrize("value", ["mini_ecommerce", "web", "spa", ""])
def test_unsupported_application_type_is_rejected(client, payload, value: str) -> None:
    """The type vocabulary is closed, and carries no target-specific value."""
    assert client.post("/targets", json=payload(type=value)).status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "not-a-url",
        "//example.com",
    ],
)
def test_non_http_urls_are_rejected(client, payload, url: str) -> None:
    assert client.post("/targets", json=payload(base_url=url)).status_code == 422
    assert client.post("/targets", json=payload(api_url=url)).status_code == 422


def test_a_non_http_login_url_is_rejected(client, payload) -> None:
    response = client.post(
        "/targets",
        json=payload(authentication={**FORM_AUTH, "login_url": "javascript:alert(1)"}),
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("name", ["", "   "])
def test_a_meaningless_name_is_rejected(client, payload, name: str) -> None:
    assert client.post("/targets", json=payload(name=name)).status_code == 422


def test_a_source_path_is_stored_as_text_and_not_resolved(client, cleanup, payload) -> None:
    """A source path is a string to hand to a scanner later, nothing more."""
    created = _create(
        client, cleanup, payload(source_path=r"C:\does\not\exist\anywhere")
    )
    assert created["source_path"] == r"C:\does\not\exist\anywhere"


# --- identity and backward compatibility ------------------------------


def test_updating_a_profile_preserves_the_target_id(client, cleanup, payload) -> None:
    """Assessments reference targets by id; an edit must never change it."""
    created = _create(client, cleanup, payload())
    original_id = created["id"]

    updated = client.patch(
        f"/targets/{original_id}",
        json={"environment": "test", "ownership_status": "owned"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == original_id
    assert updated.json()["created_at"] == created["created_at"]


def test_a_phase_one_document_reads_back_as_a_complete_profile(settings) -> None:
    """A target registered before Phase 12 is never rewritten, only filled in.

    The document is inserted exactly as Phase 1 wrote them - no environment,
    no policy, no authentication block - and has to come back through the API
    as a complete, safely defaulted profile.
    """
    with MongoClient(settings.mongodb_uri) as direct:
        collection = direct[settings.mongodb_database]["targets"]
        legacy = {
            "name": f"pytest-legacy-{uuid4().hex[:10]}",
            "base_url": "http://localhost:3000",
            "api_url": None,
            "type": "web_application",
            "source_path": None,
            "description": "Written in the Phase 1 shape.",
            "enabled": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        result = collection.insert_one(dict(legacy))
        target_id = str(result.inserted_id)

        try:
            stored = collection.find_one({"_id": result.inserted_id})
            assert "security_policy" not in stored, "the document must stay as written"

            filled = with_profile_defaults(stored)
            assert filled["environment"] == Environment.LOCAL.value
            assert filled["security_policy"] == PROFILE_DEFAULTS["security_policy"]
            assert filled["authentication"] == PROFILE_DEFAULTS["authentication"]

            # And unchanged on disk after being read.
            assert "security_policy" not in collection.find_one({"_id": result.inserted_id})
        finally:
            collection.delete_one({"_id": ObjectId(target_id)})


def test_a_legacy_target_is_served_by_the_api_with_safe_defaults(
    client: TestClient, settings
) -> None:
    with MongoClient(settings.mongodb_uri) as direct:
        collection = direct[settings.mongodb_database]["targets"]
        result = collection.insert_one(
            {
                "name": f"pytest-legacy-{uuid4().hex[:10]}",
                "base_url": "http://localhost:3000",
                "api_url": None,
                "type": "web_application",
                "source_path": None,
                "description": "",
                "enabled": True,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        target_id = str(result.inserted_id)
        try:
            response = client.get(f"/targets/{target_id}")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["security_policy"]["authorized_for_testing"] is False
            assert body["environment"] == "local"
            assert body["ownership_status"] == "unknown"
            assert body["authentication"]["enabled"] is False

            # It also appears correctly in the list, which is what the UI reads.
            listed = [t for t in client.get("/targets").json() if t["id"] == target_id]
            assert listed and listed[0]["security_policy"]["authorized_for_testing"] is False
        finally:
            collection.delete_one({"_id": ObjectId(target_id)})


def test_a_partially_written_block_keeps_what_it_has(settings) -> None:
    """A half-written block gains the missing keys, not a different answer."""
    filled = with_profile_defaults(
        {"name": "x", "security_policy": {"authorized_for_testing": True}}
    )
    assert filled["security_policy"]["authorized_for_testing"] is True
    assert filled["security_policy"]["allow_security_scanning"] is False


def test_unknown_stored_keys_in_a_block_are_ignored(settings) -> None:
    """A key this version does not know is not carried into the response."""
    filled = with_profile_defaults(
        {"name": "x", "security_policy": {"authorized_for_testing": True, "allow_everything": True}}
    )
    assert "allow_everything" not in filled["security_policy"]
