"""Test account business logic.

Every method is scoped to one target. An account is addressed by its target
*and* its id, and a mismatched pair is a 404 rather than a successful read,
so an identity registered for one application can never be reached through
another. That is the whole safety property of this service: Phase 18 will
use these accounts to ask whether a target keeps identities apart, and a
registry that mixed them up would make the answer meaningless.

No secret passes through this module. The documents carry the *name* of an
environment variable; the value behind it is never read here, and the only
thing the service reports about it is whether it is set.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.engines.security.credentials import CredentialResolver
from app.models.test_account import (
    LIST_SORT,
    document_to_response,
    ensure_indexes,
    get_collection,
)
from app.schemas.test_account import TestAccountCreate, TestAccountUpdate
from app.services.target_service import TargetService

logger = logging.getLogger(__name__)


class TestAccountServiceError(Exception):
    """Base class for test account failures."""


class InvalidTestAccountIdError(TestAccountServiceError):
    """The supplied id is not a well-formed MongoDB ObjectId."""


class TestAccountNotFoundError(TestAccountServiceError):
    """No such account exists on that target."""


class DuplicateTestAccountError(TestAccountServiceError):
    """The target already has an account with this name."""


def _now() -> datetime:
    """Current UTC time at MongoDB's millisecond precision, as elsewhere."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _to_object_id(account_id: str) -> ObjectId:
    if not ObjectId.is_valid(account_id):
        raise InvalidTestAccountIdError(f"{account_id!r} is not a valid account id.")
    return ObjectId(account_id)


#: One resolver for the service. It reads the process environment, so it
#: holds no state worth per-request construction.
_RESOLVER = CredentialResolver()


def _with_availability(document: dict[str, Any]) -> dict[str, Any]:
    """Add the read-only "is this account's configuration complete" flag.

    Asks the resolver the yes/no question and throws away everything else.
    The value itself is never read here, returned, stored or logged - an
    operator needs to know whether there is setup left to do, which is not
    the same as being shown the secret.

    A disabled account reports ``False`` because it is not usable, which is
    the question being asked.
    """
    document["credential_available"] = _RESOLVER.is_resolvable(document)
    return document


#: Two uniqueness rules can produce the conflict, so the message names both
#: rather than asserting which one it was. Mongo reports the index, but the
#: caller's useful question is "what do I have to change", and either field
#: answers it.
_DUPLICATE_MESSAGE = (
    "This target already has a test account with that name, or one with that "
    "username. Both are unique within a target."
)


class TestAccountService:
    """CRUD over the test accounts of one target at a time."""

    def __init__(self, db: AsyncDatabase, targets: TargetService) -> None:
        self._collection = get_collection(db)
        self._db = db
        self._targets = targets

    async def ensure_indexes(self) -> None:
        await ensure_indexes(self._db)

    async def _require_target(self, target_id: str) -> dict[str, Any]:
        """Resolve the target, or raise the registry's own error.

        Going through the registry rather than around it means an unknown or
        malformed target id produces exactly the response it does everywhere
        else, and an account can never be attached to a target that is not
        there.
        """
        return await self._targets.get(target_id)

    async def create(
        self, target_id: str, payload: TestAccountCreate
    ) -> dict[str, Any]:
        """Register an identity for one target."""
        target = await self._require_target(target_id)

        timestamp = _now()
        document = payload.model_dump(mode="json")
        # The target comes from the path, never from the body, so an account
        # cannot be filed against a different application than the one the
        # caller addressed.
        document["target_id"] = target["id"]
        document["created_at"] = timestamp
        document["updated_at"] = timestamp

        try:
            result = await self._collection.insert_one(document)
        except DuplicateKeyError as exc:
            raise DuplicateTestAccountError(_DUPLICATE_MESSAGE) from exc

        logger.info(
            "Registered test account %r (id=%s) for target %s",
            payload.name,
            result.inserted_id,
            target["id"],
        )
        return _with_availability(document_to_response(document))

    async def list_for_target(self, target_id: str) -> list[dict[str, Any]]:
        """Every account belonging to one target, newest first."""
        target = await self._require_target(target_id)
        documents = (
            await self._collection.find({"target_id": target["id"]})
            .sort(LIST_SORT)
            .to_list(length=None)
        )
        return [_with_availability(document_to_response(d)) for d in documents]

    async def get(self, target_id: str, account_id: str) -> dict[str, Any]:
        """One account, looked up by target *and* id.

        Both halves are part of the query. An account of another target is
        not found here rather than returned, so the nesting in the URL is a
        real boundary and not decoration.
        """
        target = await self._require_target(target_id)
        document = await self._collection.find_one(
            {"_id": _to_object_id(account_id), "target_id": target["id"]}
        )
        if document is None:
            raise TestAccountNotFoundError(
                f"No test account with id {account_id} on target {target_id}."
            )
        return _with_availability(document_to_response(document))

    async def update(
        self, target_id: str, account_id: str, payload: TestAccountUpdate
    ) -> dict[str, Any]:
        """Apply a partial update to one account of one target."""
        target = await self._require_target(target_id)
        changes = payload.changes()

        if not changes:
            return await self.get(target_id, account_id)

        changes["updated_at"] = _now()

        try:
            document = await self._collection.find_one_and_update(
                {"_id": _to_object_id(account_id), "target_id": target["id"]},
                {"$set": changes},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise DuplicateTestAccountError(_DUPLICATE_MESSAGE) from exc

        if document is None:
            raise TestAccountNotFoundError(
                f"No test account with id {account_id} on target {target_id}."
            )

        logger.info(
            "Updated test account %s on target %s (%s)",
            account_id,
            target_id,
            ", ".join(sorted(changes)),
        )
        return _with_availability(document_to_response(document))

    async def delete(self, target_id: str, account_id: str) -> None:
        """Remove one account of one target."""
        target = await self._require_target(target_id)
        result = await self._collection.delete_one(
            {"_id": _to_object_id(account_id), "target_id": target["id"]}
        )
        if result.deleted_count == 0:
            raise TestAccountNotFoundError(
                f"No test account with id {account_id} on target {target_id}."
            )
        logger.info("Deleted test account %s from target %s", account_id, target_id)

    async def count_for_target(self, target_id: str) -> int:
        """How many accounts a target still has. Used by the delete guard."""
        return await self._collection.count_documents({"target_id": target_id})
