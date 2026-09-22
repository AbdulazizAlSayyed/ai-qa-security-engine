"""Credential resolution, the owned-test-environment flag, and the
authorization placeholder's readiness reporting.

These are pure unit tests: no database, no network, no target. The resolver
is handed its own environment mapping, so nothing here depends on - or
touches - the real process environment except where that is the point.

The property being defended throughout is that a password can be *used* but
not *seen*: not in a repr, not in a log line, not in an exception, not in a
serialised model.
"""

from __future__ import annotations

import json
import logging
import pickle

import pytest

from app.engines.security.api_probes import (
    AuthorizationReadiness,
    authorization_probes_placeholder,
)
from app.engines.security.credentials import (
    CredentialError,
    CredentialResolver,
    RuntimeCredential,
)
from app.engines.security.models import ComponentStatus
from app.schemas.target import TargetCreate
from app.schemas.test_account import TestAccountCreate

SECRET = "correct-horse-battery-staple"

ACCOUNT = {
    "name": "Admin",
    "username": "admin@test.local",
    "enabled": True,
    "credential_reference": {"username_env": None, "password_env": "AIQASE_PW_ADMIN"},
}


# --- resolution ---------------------------------------------------------


def test_resolves_a_password_from_the_named_variable() -> None:
    resolver = CredentialResolver({"AIQASE_PW_ADMIN": SECRET})
    credential = resolver.resolve(ACCOUNT)

    assert credential.username == "admin@test.local"
    assert credential.password == SECRET
    assert credential.source == "env:AIQASE_PW_ADMIN"


def test_username_env_overrides_the_stored_username() -> None:
    """A username that also comes from the environment can be rotated there."""
    resolver = CredentialResolver(
        {"AIQASE_PW_ADMIN": SECRET, "AIQASE_USER_ADMIN": "rotated@test.local"}
    )
    account = {
        **ACCOUNT,
        "credential_reference": {
            "username_env": "AIQASE_USER_ADMIN",
            "password_env": "AIQASE_PW_ADMIN",
        },
    }
    assert resolver.resolve(account).username == "rotated@test.local"


def test_a_missing_variable_is_a_controlled_error_naming_it() -> None:
    """Never substituted, never guessed, never silently skipped."""
    resolver = CredentialResolver({})
    with pytest.raises(CredentialError) as caught:
        resolver.resolve(ACCOUNT)

    assert caught.value.missing == ("AIQASE_PW_ADMIN",)
    assert "AIQASE_PW_ADMIN" in str(caught.value)


def test_an_empty_variable_counts_as_missing() -> None:
    resolver = CredentialResolver({"AIQASE_PW_ADMIN": "   "})
    with pytest.raises(CredentialError):
        resolver.resolve(ACCOUNT)


def test_an_account_without_a_reference_cannot_resolve() -> None:
    resolver = CredentialResolver({"AIQASE_PW_ADMIN": SECRET})
    with pytest.raises(CredentialError) as caught:
        resolver.resolve({**ACCOUNT, "credential_reference": {}})
    assert "password_env" in str(caught.value)


def test_a_disabled_account_does_not_resolve() -> None:
    """Disabling an identity takes it out of use, not just out of a list."""
    resolver = CredentialResolver({"AIQASE_PW_ADMIN": SECRET})
    with pytest.raises(CredentialError) as caught:
        resolver.resolve({**ACCOUNT, "enabled": False})
    assert "disabled" in str(caught.value)


def test_an_account_with_no_username_anywhere_cannot_resolve() -> None:
    resolver = CredentialResolver({"AIQASE_PW_ADMIN": SECRET})
    with pytest.raises(CredentialError):
        resolver.resolve({**ACCOUNT, "username": None})


def test_is_resolvable_answers_without_returning_anything() -> None:
    assert CredentialResolver({"AIQASE_PW_ADMIN": SECRET}).is_resolvable(ACCOUNT) is True
    assert CredentialResolver({}).is_resolvable(ACCOUNT) is False


# --- non-disclosure -----------------------------------------------------


def test_the_password_is_absent_from_every_rendering() -> None:
    """repr, str and format are the three ways a value reaches a log line."""
    credential = RuntimeCredential(username="admin@test.local", password=SECRET)

    for rendered in (repr(credential), str(credential), f"{credential}", format(credential)):
        assert SECRET not in rendered
        assert "<redacted>" in rendered
        assert "admin@test.local" in rendered


def test_the_password_does_not_reach_a_log_record(caplog) -> None:
    """The realistic accident: someone logs the object."""
    credential = RuntimeCredential(username="admin@test.local", password=SECRET)
    logger = logging.getLogger("test_credentials")

    with caplog.at_level(logging.INFO):
        logger.info("using %s", credential)
        logger.info("using %r", credential)
        logger.info(f"using {credential}")

    assert SECRET not in caplog.text
    assert caplog.text.count("<redacted>") == 3


def test_an_exception_never_carries_the_value() -> None:
    resolver = CredentialResolver({"AIQASE_PW_ADMIN": SECRET})
    with pytest.raises(CredentialError) as caught:
        resolver.resolve({**ACCOUNT, "username": None})

    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)


def test_the_credential_is_not_a_serialisable_model() -> None:
    """Nothing can hand it to a JSON encoder or a pydantic response by accident."""
    credential = RuntimeCredential(username="admin@test.local", password=SECRET)

    assert not hasattr(credential, "model_dump")
    assert not hasattr(credential, "dict")
    with pytest.raises(TypeError):
        json.dumps(credential)


def test_a_pickled_credential_still_does_not_render_the_value() -> None:
    """Round-tripping must not produce an object with a leaky repr."""
    restored = pickle.loads(
        pickle.dumps(RuntimeCredential(username="a@test.local", password=SECRET))
    )
    assert SECRET not in repr(restored)
    assert restored.password == SECRET


def test_the_account_schema_has_nowhere_to_put_a_password() -> None:
    account = TestAccountCreate(name="Admin", role="admin", username="a@test.local")
    dumped = account.model_dump()

    assert "password" not in dumped
    assert set(dumped["credential_reference"]) == {"username_env", "password_env"}
    assert SECRET not in json.dumps(dumped)


# --- owned_test_environment ---------------------------------------------


def test_owned_test_environment_defaults_to_false() -> None:
    assert TargetCreate(name="x", base_url="http://localhost:3000").owned_test_environment is False


def test_declaring_an_owned_test_environment_grants_nothing_by_itself() -> None:
    """The flag is a precondition, not a switch. Nothing is enabled by it."""
    target = TargetCreate(
        name="x", base_url="http://localhost:3000", owned_test_environment=True
    )

    assert target.owned_test_environment is True
    assert target.security_policy.allow_state_changing_requests is False
    assert target.security_policy.allow_security_scanning is False
    assert target.security_policy.allow_authenticated_testing is False
    assert target.security_policy.authorized_for_testing is False


def test_state_changing_requests_need_the_declaration() -> None:
    with pytest.raises(ValueError, match="owned_test_environment"):
        TargetCreate(
            name="x",
            base_url="http://localhost:3000",
            owned_test_environment=False,
            security_policy={
                "authorized_for_testing": True,
                "allow_state_changing_requests": True,
            },
        )


def test_state_changing_requests_are_allowed_once_both_are_declared() -> None:
    target = TargetCreate(
        name="x",
        base_url="http://localhost:3000",
        environment="local",
        owned_test_environment=True,
        security_policy={
            "authorized_for_testing": True,
            "allow_state_changing_requests": True,
        },
    )
    assert target.security_policy.allow_state_changing_requests is True


# --- the authorization placeholder --------------------------------------


def test_the_placeholder_skips_with_nothing_configured() -> None:
    result = authorization_probes_placeholder()

    assert result.status is ComponentStatus.SKIPPED
    assert "owned test environment" in result.detail
    assert "no authentication is configured" in result.detail
    assert "no enabled test account" in result.detail


@pytest.mark.parametrize(
    ("readiness", "expected"),
    [
        (
            AuthorizationReadiness(
                owned_test_environment=False,
                authentication_configured=True,
                usable_accounts=2,
                distinct_roles=2,
            ),
            "owned test environment",
        ),
        (
            AuthorizationReadiness(
                owned_test_environment=True,
                authentication_configured=False,
                usable_accounts=2,
                distinct_roles=2,
            ),
            "no authentication is configured",
        ),
        (
            AuthorizationReadiness(
                owned_test_environment=True,
                authentication_configured=True,
                usable_accounts=0,
                distinct_roles=0,
            ),
            "no enabled test account",
        ),
        (
            AuthorizationReadiness(
                owned_test_environment=True,
                authentication_configured=True,
                usable_accounts=1,
                distinct_roles=1,
            ),
            "only one role",
        ),
    ],
)
def test_the_skip_reason_names_what_is_actually_missing(
    readiness: AuthorizationReadiness, expected: str
) -> None:
    """The old reason said the same thing whatever was wrong."""
    result = authorization_probes_placeholder(readiness)
    assert result.status is ComponentStatus.SKIPPED
    assert expected in result.detail


def test_a_fully_configured_target_is_told_the_engine_is_what_is_missing() -> None:
    result = authorization_probes_placeholder(
        AuthorizationReadiness(
            owned_test_environment=True,
            authentication_configured=True,
            usable_accounts=2,
            distinct_roles=2,
        )
    )

    assert result.status is ComponentStatus.SKIPPED, "Phase 12 must not probe"
    assert "not implemented yet" in result.detail
    assert result.metadata["usable_accounts"] == 2
    assert result.metadata["distinct_roles"] == 2


def test_the_placeholder_never_reports_anything_but_skipped() -> None:
    """No configuration turns this into a run. That is Phase 18's job."""
    for readiness in (
        None,
        AuthorizationReadiness(),
        AuthorizationReadiness(
            owned_test_environment=True,
            authentication_configured=True,
            usable_accounts=5,
            distinct_roles=3,
        ),
    ):
        result = authorization_probes_placeholder(readiness)
        assert result.status is ComponentStatus.SKIPPED
        assert result.findings == []
