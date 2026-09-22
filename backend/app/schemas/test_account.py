"""Request and response schemas for test accounts.

One rule dominates this module: **a password never enters it**. There is no
field to put one in, ``extra="forbid"`` turns an attempt into a 422 rather
than a silently ignored key, and ``credential_reference`` is validated as an
environment-variable *name* so a value pasted into it is rejected on shape
alone.

That makes the protection structural rather than procedural. Nothing here
has to remember to redact a secret on the way out, because nothing on the
way in could have carried one.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.models.test_account import ANONYMOUS_ROLES, DEFAULT_ROLE

MAX_NAME_LENGTH = 120
MAX_USERNAME_LENGTH = 200
MAX_PURPOSE_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 2000
MAX_CREDENTIAL_REFERENCE_LENGTH = 100
MAX_ROLE_LENGTH = 60

#: An environment variable name: leading letter, then upper-case letters,
#: digits and underscores. Deliberately narrow. A password, a token or a
#: connection string will not match it, so a caller who mistakes this field
#: for "the password" is told so instead of storing one.
CREDENTIAL_REFERENCE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: A role name: letters, digits, underscore and hyphen. Open on purpose -
#: an application's roles are its own, and this platform has no business
#: owning a taxonomy of them. The pattern only keeps the value a label.
ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

#: Spellings that mean a credential was pasted into a free-text field.
_CREDENTIAL_MARKERS = ("password=", "password:", "passwd=", "secret=", "token=")


def blank_is_absent(value: Any) -> Any:
    """Treat an all-whitespace optional string as not supplied."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def validate_credential_reference(value: Any) -> Any:
    """Accept an environment variable name, and nothing that looks like a value.

    Shared by the create and update schemas so both reject the same thing.
    The narrow pattern is the protection: a password, a token or a
    connection string does not match it, so a caller who mistakes this field
    for "the password" is told so rather than having one stored.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("credential_reference must be the name of an env var.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if not CREDENTIAL_REFERENCE_PATTERN.match(cleaned):
        raise ValueError(
            "credential_reference is the NAME of an environment variable "
            "(e.g. E2E_ADMIN_PASSWORD), not a password. Use upper-case letters, "
            "digits and underscores, starting with a letter."
        )
    return cleaned


def validate_role(value: Any) -> Any:
    """A role is a label the target's own application defines."""
    if value is None:
        return DEFAULT_ROLE
    if not isinstance(value, str):
        raise ValueError("role must be a name, e.g. 'admin' or 'manager'.")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("role must not be empty.")
    if not ROLE_PATTERN.match(cleaned):
        raise ValueError(
            "role must start with a letter and contain only letters, digits, "
            "underscores or hyphens, e.g. 'admin', 'manager', 'read-only'."
        )
    return cleaned


def reject_credentials_in_text(value: str | None, field_name: str) -> str | None:
    """Keep free text free of credentials.

    A field meant for notes is where a password ends up when someone is in a
    hurry. This does not make that impossible, but it refuses the obvious
    spellings and says why.
    """
    if value is None:
        return None
    lowered = value.lower()
    for marker in _CREDENTIAL_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"{field_name} must not contain credentials. Store the name of an "
                "environment variable in credential_reference instead."
            )
    return value


class CredentialReference(BaseModel):
    """Where this account's credentials live - never what they are.

    Two environment variable *names*. The operator sets the values in the
    environment of the machine running the backend; this record says which
    names to look under, and :class:`~app.engines.security.credentials.
    CredentialResolver` is the only thing that ever reads them.

    ``username_env`` is optional because a username is not a secret and is
    usually simpler to record directly on the account. When it is set, it
    wins: an account whose username also comes from the environment can be
    rotated without touching the database.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    username_env: str | None = Field(
        default=None,
        max_length=MAX_CREDENTIAL_REFERENCE_LENGTH,
        description="NAME of the env var holding the username, if it comes from there.",
        examples=["AIQASE_TEST_USER_ADMIN"],
    )
    password_env: str | None = Field(
        default=None,
        max_length=MAX_CREDENTIAL_REFERENCE_LENGTH,
        description="NAME of the env var holding the password. Never the password.",
        examples=["AIQASE_TEST_PASSWORD_ADMIN"],
    )

    @field_validator("username_env", "password_env", mode="before")
    @classmethod
    def _names_only(cls, value: Any) -> Any:
        return validate_credential_reference(value)

    @property
    def is_configured(self) -> bool:
        """Does this reference name anywhere to look for a password?"""
        return bool(self.password_env)


class TestAccountBase(BaseModel):
    """Fields a client may supply when describing a test account."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=MAX_NAME_LENGTH,
        description="Human-readable name, unique within the target.",
        examples=["Admin test account"],
    )
    role: str = Field(
        default=DEFAULT_ROLE,
        max_length=MAX_ROLE_LENGTH,
        description=(
            "The role this identity has in the target's own application - any name "
            "that application uses. Metadata, not an authorization rule."
        ),
        examples=["admin", "manager", "customer"],
    )
    purpose: str = Field(
        default="",
        max_length=MAX_PURPOSE_LENGTH,
        description="What this identity is kept for, in the operator's own words.",
        examples=["authorization_test_user"],
    )
    username: str | None = Field(
        default=None,
        max_length=MAX_USERNAME_LENGTH,
        description="The identity's username. Never a password.",
        examples=["admin@test.local"],
    )
    credential_reference: CredentialReference = Field(
        default_factory=CredentialReference,
        description=(
            "Environment variable NAMES for this account's credentials. Never the "
            "credentials themselves."
        ),
    )
    description: str = Field(
        default="",
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Free-text notes about the account.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether a future phase may use this identity.",
    )

    @field_validator("username", mode="before")
    @classmethod
    def _blank_username_is_absent(cls, value: Any) -> Any:
        return blank_is_absent(value)

    @field_validator("role", mode="before")
    @classmethod
    def _role_is_a_label(cls, value: Any) -> Any:
        return validate_role(value)

    @field_validator("purpose", "description", "name")
    @classmethod
    def _no_credentials_in_text(cls, value: str, info: ValidationInfo) -> str:
        return reject_credentials_in_text(value, info.field_name or "field") or ""

    @model_validator(mode="after")
    def _identity_matches_role(self) -> TestAccountBase:
        """An anonymous identity has nothing to authenticate with.

        Recording a username or a credential against it would describe an
        account that is, by definition, not one - and a later phase reading
        this record would have no way to tell which half to believe.
        """
        has_credential = bool(
            self.credential_reference.username_env or self.credential_reference.password_env
        )
        if self.role.lower() in ANONYMOUS_ROLES and (self.username or has_credential):
            raise ValueError(
                "an anonymous account represents an unauthenticated visitor, so it "
                "carries neither a username nor a credential_reference."
            )
        return self


class TestAccountCreate(TestAccountBase):
    """Payload for ``POST /targets/{target_id}/test-accounts``.

    ``target_id`` is not a field: it comes from the path, so an account
    cannot be created against a target other than the one addressed.
    """


class TestAccountUpdate(BaseModel):
    """Payload for ``PATCH /targets/{target_id}/test-accounts/{account_id}``.

    Every field is optional; only what the client sends is written.
    ``target_id`` is absent on purpose - an account belongs to the target it
    was created under, and moving it would silently repoint an identity at
    an application it was never meant for.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    role: str | None = Field(default=None, max_length=MAX_ROLE_LENGTH)
    purpose: str | None = Field(default=None, max_length=MAX_PURPOSE_LENGTH)
    username: str | None = Field(default=None, max_length=MAX_USERNAME_LENGTH)
    #: Replaced whole, like the target's nested blocks, so a half-applied
    #: reference cannot point a username and a password at different accounts.
    credential_reference: CredentialReference | None = None
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    enabled: bool | None = None

    @field_validator("username", mode="before")
    @classmethod
    def _blank_username_is_absent(cls, value: Any) -> Any:
        return blank_is_absent(value)

    @field_validator("role", mode="before")
    @classmethod
    def _role_is_a_label(cls, value: Any) -> Any:
        return validate_role(value) if value is not None else None

    @field_validator("purpose", "description", "name")
    @classmethod
    def _no_credentials_in_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        return reject_credentials_in_text(value, info.field_name or "field")

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(mode="json", exclude_unset=True)


class TestAccountResponse(BaseModel):
    """A test account as the API exposes it.

    Safe metadata only. ``credential_available`` reports whether the named
    environment variable is currently set on the server, which is what an
    operator needs in order to finish configuring the account. It is a
    boolean derived at read time; the value itself is never read into the
    response, stored, or logged.
    """

    id: str = Field(description="String form of the MongoDB ObjectId.")
    target_id: str
    name: str
    role: str
    purpose: str
    username: str | None
    credential_reference: CredentialReference
    credential_available: bool = Field(
        default=False,
        description=(
            "Whether every environment variable this account names is currently set "
            "on the server. Never the values, and never which one is missing."
        ),
    )
    description: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TestAccountDeleteResponse(BaseModel):
    """Confirmation that a test account was removed."""

    deleted: bool = True
    id: str
