"""Request and response schemas for the target registry.

From Phase 12 a target carries a profile: environment, ownership, how it
authenticates, and what testing it is authorised for. Two rules run through
all of it.

**Fail closed.** Every capability defaults to off, and an unrecorded answer
is never read as consent. ``authorized_for_testing`` gates the rest: with it
false, no ``allow_*`` flag may be true, so a permission cannot be smuggled in
one field at a time.

**Configuration, not behaviour.** The authentication block describes how a
target *would* be authenticated against. Nothing here logs in, and no engine
consumes it yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.models.target import (
    AuthMethod,
    Environment,
    OwnershipStatus,
    TargetType,
    TokenLocation,
)

MAX_NAME_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 2000
MAX_SOURCE_PATH_LENGTH = 500
MAX_FIELD_NAME_LENGTH = 100

#: Methods whose configuration is a login form the platform would fill in.
#: Only these require the form's own field names to be recorded.
FORM_METHODS = frozenset({AuthMethod.FORM_LOGIN})

#: Methods that identify the session by a named cookie.
COOKIE_METHODS = frozenset({AuthMethod.COOKIE})

MAX_NOTES_LENGTH = 1000

# Used for validation only. The original string is what gets stored, because
# pydantic's URL type normalises "http://localhost:3000" into
# "http://localhost:3000/", and a target's URL should come back exactly as it
# was registered.
_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def _clean_optional_url(value: str | None, field_name: str) -> str | None:
    """Validate an optional URL without rewriting it. Blank becomes ``None``."""
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    try:
        _URL_ADAPTER.validate_python(cleaned)
    except ValidationError as exc:
        raise ValueError(
            f"{field_name} must be a valid http(s) URL, for example http://localhost:3000"
        ) from exc

    return cleaned


def _clean_optional_text(value: str | None) -> str | None:
    """Treat an all-whitespace optional string as absent."""
    if value is None:
        return None
    return value.strip() or None


class AuthenticationProfile(BaseModel):
    """How the platform *would* authenticate against this target.

    Configuration only. No credential of any kind belongs here: the field
    names describe the login form, and the account identities and their
    credential references live on test accounts.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Whether this target has authentication a future phase may use.",
    )
    method: AuthMethod = Field(
        default=AuthMethod.NONE,
        description="Authentication style, e.g. a login form or a bearer token.",
    )
    login_url: str | None = Field(
        default=None,
        description="Where a form login is submitted.",
        examples=["http://localhost:3000/login"],
    )
    username_field: str | None = Field(
        default=None,
        max_length=MAX_FIELD_NAME_LENGTH,
        description="Name or test id of the username input on the login form.",
    )
    password_field: str | None = Field(
        default=None,
        max_length=MAX_FIELD_NAME_LENGTH,
        description="Name or test id of the password input. Never a password.",
    )
    cookie_name: str | None = Field(
        default=None,
        max_length=MAX_FIELD_NAME_LENGTH,
        description="Name of the session cookie. Never its value.",
        examples=["session"],
    )
    token_location: TokenLocation = Field(
        default=TokenLocation.NONE,
        description="Where the target keeps the credential once authenticated.",
    )
    notes: str = Field(
        default="",
        max_length=MAX_NOTES_LENGTH,
        description="Anything a later phase would need to know. Never a credential.",
    )

    @field_validator("login_url")
    @classmethod
    def _validate_login_url(cls, value: str | None) -> str | None:
        return _clean_optional_url(value, "login_url")

    @field_validator("username_field", "password_field", "cookie_name")
    @classmethod
    def _validate_field_names(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("notes")
    @classmethod
    def _notes_carry_no_credentials(cls, value: str) -> str:
        """A free-text box next to a login form invites a pasted password."""
        lowered = value.lower()
        for marker in ("password=", "password:", "passwd=", "secret=", "token="):
            if marker in lowered:
                raise ValueError(
                    "authentication.notes must not contain credentials. Credentials "
                    "are referenced by environment variable name on a test account."
                )
        return value

    @model_validator(mode="after")
    def _coherent_configuration(self) -> AuthenticationProfile:
        """Reject configurations that could not actually be carried out.

        A profile that says "enabled" while naming no method, or a form
        login with no form fields, is an intention rather than a
        configuration. Catching it here means a later phase can trust the
        record instead of re-deriving what is missing.
        """
        if not self.enabled:
            if self.method is not AuthMethod.NONE:
                raise ValueError(
                    "authentication.method must be 'none' while authentication is disabled."
                )
            return self

        if self.method is AuthMethod.NONE:
            raise ValueError(
                "authentication.enabled requires a method other than 'none'."
            )

        if self.method in FORM_METHODS:
            missing = [
                name
                for name, value in (
                    ("login_url", self.login_url),
                    ("username_field", self.username_field),
                    ("password_field", self.password_field),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"a '{self.method.value}' login needs {', '.join(missing)}."
                )

        if self.method in COOKIE_METHODS and not self.cookie_name:
            raise ValueError(
                f"a '{self.method.value}' session needs cookie_name, otherwise a later "
                "phase cannot tell which cookie carries the session."
            )

        return self


class SecurityPolicy(BaseModel):
    """What this platform is permitted to do to the target.

    A technical safety control, not a legal statement. Every capability is
    off by default and each one has to be turned on deliberately, because
    the cost of a wrong default here is a scan against something nobody
    agreed to.
    """

    model_config = ConfigDict(extra="forbid")

    authorized_for_testing: bool = Field(
        default=False,
        description="Whether this platform is permitted to test this target at all.",
    )
    allow_security_scanning: bool = Field(
        default=False,
        description="Whether the security engine may scan it.",
    )
    allow_authenticated_testing: bool = Field(
        default=False,
        description="Whether test-account identities may be used against it.",
    )
    allow_state_changing_requests: bool = Field(
        default=False,
        description="Whether anything may send a request that modifies data.",
    )

    @property
    def granted(self) -> list[str]:
        """The capability flags currently turned on."""
        return [
            name
            for name in (
                "allow_security_scanning",
                "allow_authenticated_testing",
                "allow_state_changing_requests",
            )
            if getattr(self, name)
        ]

    @model_validator(mode="after")
    def _authorization_gates_every_capability(self) -> SecurityPolicy:
        """No capability may be granted without authorisation for the target.

        The gate is what makes the default safe rather than merely
        conventional: without it, ``allow_state_changing_requests`` alone
        would read as permission, and a future engine would have to
        remember to check two fields instead of trusting one.
        """
        if not self.authorized_for_testing and self.granted:
            raise ValueError(
                "security_policy.authorized_for_testing must be true before "
                f"{', '.join(self.granted)} may be enabled."
            )
        return self


class TargetBase(BaseModel):
    """Fields a client may supply when describing a target.

    ``extra="forbid"`` is deliberate: it makes an attempt to set ``_id`` or
    ``created_at`` a clear 422 instead of being silently ignored.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=MAX_NAME_LENGTH,
        description="Human-readable name, unique per base/API URL combination.",
        examples=["Mini E-Commerce"],
    )
    base_url: str | None = Field(
        default=None,
        description="Where the application's UI is served.",
        examples=["http://localhost:3000"],
    )
    api_url: str | None = Field(
        default=None,
        description="Where the application's API is served.",
        examples=["http://localhost:4000"],
    )
    type: TargetType = Field(
        default=TargetType.WEB_APPLICATION,
        description="Which surfaces this target exposes.",
    )
    source_path: str | None = Field(
        default=None,
        max_length=MAX_SOURCE_PATH_LENGTH,
        description="Local path to the source tree, when static analysis is possible.",
    )
    description: str = Field(
        default="",
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Free-text notes about the target.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether assessments may run against this target.",
    )
    environment: Environment = Field(
        default=Environment.LOCAL,
        description="Where the target runs. Production is treated conservatively.",
    )
    ownership_status: OwnershipStatus = Field(
        default=OwnershipStatus.UNKNOWN,
        description="How this platform comes to be pointed at the target.",
    )
    owned_test_environment: bool = Field(
        default=False,
        description=(
            "The operator declares this is their own test environment. False means "
            "only the existing non-destructive behaviour is available. True is a "
            "precondition for state-changing testing in a later phase - it does not "
            "enable anything on its own, and nothing acts on it today."
        ),
    )
    authentication: AuthenticationProfile = Field(
        default_factory=AuthenticationProfile,
        description="How the target authenticates. Configuration only; nothing logs in.",
    )
    security_policy: SecurityPolicy = Field(
        default_factory=SecurityPolicy,
        description="What this platform is permitted to do. Everything off by default.",
    )

    @field_validator("base_url", "api_url")
    @classmethod
    def _validate_urls(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _clean_optional_url(value, info.field_name or "url")

    @field_validator("source_path")
    @classmethod
    def _validate_source_path(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


def check_profile_coherence(
    environment: Environment,
    authentication: AuthenticationProfile,
    policy: SecurityPolicy,
    owned_test_environment: bool = False,
) -> None:
    """Reject combinations that are unsafe or cannot be carried out.

    Shared by the create schema and by the service's update path, because a
    patch has to be judged on the document it produces rather than on the
    fields it happens to mention. Setting ``authorized_for_testing`` to false
    on its own would otherwise leave the capabilities it was gating switched
    on.

    Raises ``ValueError`` so pydantic reports it as a 422 on create, and the
    service can translate it the same way on update.
    """
    # Writing to an application needs two separate answers: the operator is
    # permitted to test it, and the operator says it is their own test
    # environment. The second is the one that distinguishes "I may look at
    # this" from "I may change it", so it gates state-changing work on its
    # own rather than being folded into the general authorisation flag.
    if policy.allow_state_changing_requests and not owned_test_environment:
        raise ValueError(
            "allow_state_changing_requests requires owned_test_environment, an "
            "explicit declaration that this application is the operator's own "
            "test environment."
        )

    if environment is Environment.PRODUCTION:
        # Passive reading of a production system is a defensible choice to
        # make deliberately. Scanning it, or writing to it, is not something
        # this registry will hold a "yes" for.
        forbidden = [
            name
            for name in ("allow_security_scanning", "allow_state_changing_requests")
            if getattr(policy, name)
        ]
        if forbidden:
            raise ValueError(
                f"{', '.join(forbidden)} cannot be enabled for a production target. "
                "Point this profile at a non-production environment instead."
            )

    if policy.allow_authenticated_testing and not authentication.enabled:
        raise ValueError(
            "allow_authenticated_testing requires authentication.enabled, "
            "otherwise there is no configured way to authenticate."
        )


class TargetCreate(TargetBase):
    """Payload for ``POST /targets``."""

    @model_validator(mode="after")
    def _profile_is_coherent(self) -> TargetCreate:
        check_profile_coherence(
            self.environment,
            self.authentication,
            self.security_policy,
            self.owned_test_environment,
        )
        return self


class TargetUpdate(BaseModel):
    """Payload for ``PATCH /targets/{id}``.

    Every field is optional. Only fields actually present in the request body
    are written, so omitting ``base_url`` leaves it alone while sending
    ``"base_url": null`` clears it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    base_url: str | None = None
    api_url: str | None = None
    type: TargetType | None = None
    source_path: str | None = Field(default=None, max_length=MAX_SOURCE_PATH_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    enabled: bool | None = None
    environment: Environment | None = None
    ownership_status: OwnershipStatus | None = None
    owned_test_environment: bool | None = None
    # Each block is replaced whole rather than merged field by field. A
    # half-applied security policy is exactly the state the fail-closed rule
    # exists to prevent, so the client sends the policy it wants to hold.
    authentication: AuthenticationProfile | None = None
    security_policy: SecurityPolicy | None = None

    @field_validator("base_url", "api_url")
    @classmethod
    def _validate_urls(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _clean_optional_url(value, info.field_name or "url")

    @field_validator("source_path")
    @classmethod
    def _validate_source_path(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(mode="json", exclude_unset=True)


class TargetResponse(BaseModel):
    """A registered target as the API exposes it.

    The profile fields carry defaults so a target registered before Phase 12
    still serialises. Combined with ``with_profile_defaults`` on read, an old
    document answers every question a new one does, and no historical record
    has to be rewritten to make that true.
    """

    id: str = Field(description="String form of the MongoDB ObjectId.")
    name: str
    base_url: str | None
    api_url: str | None
    type: TargetType
    source_path: str | None
    description: str
    enabled: bool
    environment: Environment = Environment.LOCAL
    ownership_status: OwnershipStatus = OwnershipStatus.UNKNOWN
    owned_test_environment: bool = False
    authentication: AuthenticationProfile = Field(default_factory=AuthenticationProfile)
    security_policy: SecurityPolicy = Field(default_factory=SecurityPolicy)
    created_at: datetime
    updated_at: datetime


class TargetDeleteResponse(BaseModel):
    """Confirmation that a target was removed."""

    deleted: bool = True
    id: str
