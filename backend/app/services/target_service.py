"""Target registry business logic.

Routes translate HTTP; this module owns the rules and is the only place that
touches the ``targets`` collection. It raises its own exception types rather
than ``HTTPException`` so it stays usable from anywhere -- the orchestrator
will need to read targets in a later phase, and it is not an HTTP caller.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.models.target import (
    LIST_SORT,
    document_to_response,
    ensure_indexes,
    get_collection,
)
from app.schemas.target import TargetCreate, TargetUpdate

logger = logging.getLogger(__name__)


class TargetServiceError(Exception):
    """Base class for target registry failures."""


class InvalidTargetIdError(TargetServiceError):
    """The supplied id is not a well-formed MongoDB ObjectId."""


class TargetNotFoundError(TargetServiceError):
    """No target exists with the supplied id."""


class DuplicateTargetError(TargetServiceError):
    """Another target already has this name, base URL and API URL."""


def _now() -> datetime:
    """Current UTC time at MongoDB's precision.

    BSON dates hold milliseconds. Truncating here means the timestamp a
    client gets back from a create is byte-for-byte the one a later read
    returns, instead of differing in microseconds.
    """
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _to_object_id(target_id: str) -> ObjectId:
    if not ObjectId.is_valid(target_id):
        raise InvalidTargetIdError(f"{target_id!r} is not a valid target id.")
    return ObjectId(target_id)


_DUPLICATE_MESSAGE = (
    "A target with this name, base URL and API URL is already registered."
)


class TargetService:
    """CRUD over the target registry."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._collection = get_collection(db)
        self._db = db

    async def ensure_indexes(self) -> None:
        """Create the duplicate-prevention index."""
        await ensure_indexes(self._db)

    async def create(self, payload: TargetCreate) -> dict[str, Any]:
        """Register a new target."""
        timestamp = _now()
        document = payload.model_dump(mode="json")
        document["created_at"] = timestamp
        document["updated_at"] = timestamp

        try:
            result = await self._collection.insert_one(document)
        except DuplicateKeyError as exc:
            raise DuplicateTargetError(_DUPLICATE_MESSAGE) from exc

        logger.info("Registered target %r (id=%s)", payload.name, result.inserted_id)
        return document_to_response(document)

    async def list_all(self) -> list[dict[str, Any]]:
        """Every registered target, newest first."""
        documents = await self._collection.find({}).sort(LIST_SORT).to_list(length=None)
        return [document_to_response(document) for document in documents]

    async def get(self, target_id: str) -> dict[str, Any]:
        """One target by id."""
        document = await self._collection.find_one({"_id": _to_object_id(target_id)})
        if document is None:
            raise TargetNotFoundError(f"No target with id {target_id}.")
        return document_to_response(document)

    async def update(self, target_id: str, payload: TargetUpdate) -> dict[str, Any]:
        """Apply a partial update.

        ``_id`` and ``created_at`` are not updatable: the schema rejects them
        outright, so they can never reach the ``$set``.
        """
        object_id = _to_object_id(target_id)
        changes = payload.changes()

        if not changes:
            # An empty patch is not an error, but it should not bump
            # updated_at either - nothing changed.
            return await self.get(target_id)

        changes["updated_at"] = _now()

        try:
            document = await self._collection.find_one_and_update(
                {"_id": object_id},
                {"$set": changes},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise DuplicateTargetError(_DUPLICATE_MESSAGE) from exc

        if document is None:
            raise TargetNotFoundError(f"No target with id {target_id}.")

        logger.info("Updated target %s (%s)", target_id, ", ".join(sorted(changes)))
        return document_to_response(document)

    async def delete(self, target_id: str) -> None:
        """Remove a target."""
        result = await self._collection.delete_one({"_id": _to_object_id(target_id)})
        if result.deleted_count == 0:
            raise TargetNotFoundError(f"No target with id {target_id}.")
        logger.info("Deleted target %s", target_id)
