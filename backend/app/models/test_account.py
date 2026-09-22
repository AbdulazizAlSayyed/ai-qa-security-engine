"""Persistence layer for the ``test_accounts`` collection.

A *test account* is an identity a future phase is authorised to use against
one specific target: an admin, an ordinary user, a second user whose data
the first must not be able to reach. Phase 18 will need two such identities
to test authorization at all, which is why they are recorded now.

**No secret is stored here, and none ever will be.** The document holds a
``credential_reference``: the *name* of an environment variable the operator
sets on the machine that runs the platform. The value behind that name is
read at use time by whatever needs it, never copied into MongoDB, never
logged, never returned by the API and never rendered in the UI. A document
in this collection is therefore not worth stealing, which is the point.

This module owns everything MongoDB-shaped about a test account. Business
rules live in ``app.services.test_account_service``.
"""

from __future__ import annotations

from collections.abc import Mapping

from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "test_accounts"

#: One account name per target. Two accounts called "admin" on the same
#: target are a mistake; the same name on two different targets is not.
UNIQUE_INDEX_NAME = "uniq_test_account_identity"
UNIQUE_INDEX_KEYS = [("target_id", ASCENDING), ("name", ASCENDING)]

#: The same username twice on one target is two records for one identity,
#: which makes an authorization question ambiguous before it is asked.
#: Partial, because an anonymous account legitimately has no username and
#: several of those must be able to coexist.
UNIQUE_USERNAME_INDEX_NAME = "uniq_test_account_username"
UNIQUE_USERNAME_INDEX_KEYS = [("target_id", ASCENDING), ("username", ASCENDING)]

#: Accounts are always listed within one target, so the lookup index leads
#: with ``target_id``.
TARGET_INDEX_NAME = "test_accounts_by_target"
TARGET_INDEX_KEYS = [("target_id", ASCENDING), ("created_at", DESCENDING)]

#: "Which identities may actually be used against this target" is the
#: question a later phase asks, so it gets its own index.
ENABLED_INDEX_NAME = "test_accounts_by_target_enabled"
ENABLED_INDEX_KEYS = [("target_id", ASCENDING), ("enabled", ASCENDING)]

#: Newest first, ``_id`` breaking ties, as the target registry does.
LIST_SORT = [("created_at", DESCENDING), ("_id", DESCENDING)]

#: The role an account is given when none is supplied.
DEFAULT_ROLE = "user"

#: Role names that describe an unauthenticated visitor. Such an account has
#: no username and no credential, and saying so is the whole content of the
#: record.
#:
#: Roles are otherwise free text: an application's roles are its own, and a
#: closed vocabulary here would either exclude real ones (manager, customer,
#: reviewer) or grow into a taxonomy this platform has no business owning.
#: Nothing matches on a role in this phase.
ANONYMOUS_ROLES = frozenset({"anonymous"})

#: Offered by the UI as suggestions only. Not a constraint, and no engine
#: reads this list.
COMMON_ROLES = ("admin", "user", "manager", "customer", "readonly", "guest", "anonymous")


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the test accounts collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the uniqueness and lookup indexes. Safe to call repeatedly."""
    collection = get_collection(db)
    await collection.create_index(
        UNIQUE_INDEX_KEYS, unique=True, name=UNIQUE_INDEX_NAME
    )
    # Partial: only documents that actually carry a username take part, so
    # any number of anonymous accounts (which have none) can coexist.
    await collection.create_index(
        UNIQUE_USERNAME_INDEX_KEYS,
        unique=True,
        name=UNIQUE_USERNAME_INDEX_NAME,
        partialFilterExpression={"username": {"$type": "string"}},
    )
    await collection.create_index(TARGET_INDEX_KEYS, name=TARGET_INDEX_NAME)
    await collection.create_index(ENABLED_INDEX_KEYS, name=ENABLED_INDEX_NAME)


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a stored document into the shape the API exposes.

    Turns ``_id`` into a string ``id``. There is no secret to strip here,
    because there is no secret in the document - the schema has no field one
    could be written to.
    """
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
