"""Persistence layer for the ``targets`` collection.

A *target* is an application the platform is authorised to assess. Keeping
target definitions in the database rather than in code is what lets the QA
and security engines stay generic: adding an application later means adding
a document, not editing an engine.

From Phase 12 a target also carries a *profile*: which environment it runs
in, who owns it, how it authenticates, and what testing it is authorised
for. That is configuration describing the target. Nothing here decides what
will be tested, and nothing here performs authentication.

This module owns everything MongoDB-shaped about a target -- collection
name, indexes, sort order, and the document/API translation. Business rules
live in ``app.services.target_service``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "targets"

#: A target's identity for duplicate detection.
UNIQUE_INDEX_NAME = "uniq_target_identity"
UNIQUE_INDEX_KEYS = [
    ("name", ASCENDING),
    ("base_url", ASCENDING),
    ("api_url", ASCENDING),
]

#: Newest first. ``_id`` breaks ties, since two targets registered in the
#: same millisecond would otherwise come back in arbitrary order.
LIST_SORT = [("created_at", DESCENDING), ("_id", DESCENDING)]


class TargetType(str, Enum):
    """What kind of surface a target exposes.

    This drives which engines can meaningfully run against it later: a pure
    ``api`` target has nothing for a browser-based QA run to click.

    The vocabulary is deliberately unchanged from Phase 1. Stored
    assessments, QA runs and security runs all snapshot these exact strings,
    and the orchestrator matches on them, so renaming a member would
    invalidate history that cannot be re-derived.
    """

    WEB_APPLICATION = "web_application"
    API = "api"
    WEB_AND_API = "web_and_api"


class Environment(str, Enum):
    """Where the target runs.

    Small and controlled on purpose. ``PRODUCTION`` is the one value the
    validation layer treats more conservatively; the rest differ only as
    labels for whoever reads the registry.
    """

    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    TEST = "test"
    PRODUCTION = "production"


class OwnershipStatus(str, Enum):
    """How this platform comes to be pointed at the target.

    Recorded next to the testing policy so the two are read together.
    ``UNKNOWN`` is the default because an unrecorded answer is not consent.
    """

    OWNED = "owned"
    AUTHORIZED = "authorized"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class AuthMethod(str, Enum):
    """How a future phase would authenticate against the target.

    Configuration vocabulary only. Nothing in this phase logs in, and no
    engine reads these values yet.
    """

    NONE = "none"
    FORM_LOGIN = "form_login"
    BASIC = "basic"
    BEARER_TOKEN = "bearer_token"
    COOKIE = "cookie"
    CUSTOM = "custom"


class TokenLocation(str, Enum):
    """Where the target keeps the credential once authenticated."""

    NONE = "none"
    HEADER = "header"
    COOKIE = "cookie"
    LOCAL_STORAGE = "local_storage"
    SESSION_STORAGE = "session_storage"


#: The profile fields Phase 12 adds, with the values a document is treated as
#: having when it does not carry them. Every default is the safe one: an
#: unrecorded environment is not production, unrecorded ownership is not
#: consent, and no capability is enabled by omission.
#:
#: Targets registered in Phases 1-10 predate all of this, and are never
#: rewritten. :func:`with_profile_defaults` fills the gaps on read, so an old
#: document and a new one answer the same questions.
PROFILE_DEFAULTS: dict[str, Any] = {
    "environment": Environment.LOCAL.value,
    "ownership_status": OwnershipStatus.UNKNOWN.value,
    # The explicit safety boundary for state-changing work. False means the
    # platform has not been told this application is the operator's own test
    # environment, and an unrecorded answer is never read as one.
    "owned_test_environment": False,
    "authentication": {
        "enabled": False,
        "method": AuthMethod.NONE.value,
        "login_url": None,
        "username_field": None,
        "password_field": None,
        "cookie_name": None,
        "token_location": TokenLocation.NONE.value,
        "notes": "",
    },
    "security_policy": {
        "authorized_for_testing": False,
        "allow_security_scanning": False,
        "allow_authenticated_testing": False,
        "allow_state_changing_requests": False,
    },
}


def with_profile_defaults(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``document`` with any missing profile fields filled in.

    Backward compatibility, applied on read rather than by migration: a
    target registered before Phase 12 keeps its stored document exactly as
    it is, and still presents a complete profile. Nested blocks are merged
    key by key, so a partially written block does not lose the keys it does
    have or silently gain a permission it never recorded.
    """
    result = dict(document)
    for field, default in PROFILE_DEFAULTS.items():
        if isinstance(default, dict):
            stored = result.get(field)
            merged = dict(default)
            if isinstance(stored, Mapping):
                merged.update({k: v for k, v in stored.items() if k in default})
            result[field] = merged
        elif result.get(field) in (None, ""):
            result[field] = default
    return result


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the targets collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the duplicate-prevention index. Safe to call repeatedly.

    ``base_url`` and ``api_url`` are optional, so the schema layer always
    writes them explicitly as ``None`` rather than omitting the keys. That
    keeps every document the same shape and makes this compound unique index
    behave predictably: two targets that differ only by having an API URL
    are legitimately different and both insert fine.
    """
    await get_collection(db).create_index(
        UNIQUE_INDEX_KEYS,
        unique=True,
        name=UNIQUE_INDEX_NAME,
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a stored document into the shape the API exposes.

    Turns ``_id`` (an ObjectId) into a string ``id``, so nothing
    MongoDB-specific leaks past this boundary, and fills in any profile
    field the stored document predates. Every read goes through here, so a
    Phase 1 target and a Phase 12 target are indistinguishable to callers
    without either being rewritten on disk.
    """
    data = with_profile_defaults(document)
    data["id"] = str(data.pop("_id"))
    return data
