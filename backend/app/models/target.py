"""Persistence layer for the ``targets`` collection.

A *target* is an application the platform is authorised to assess. Keeping
target definitions in the database rather than in code is what lets the QA
and security engines stay generic: adding an application later means adding
a document, not editing an engine.

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
    """

    WEB_APPLICATION = "web_application"
    API = "api"
    WEB_AND_API = "web_and_api"


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

    The only real work is turning ``_id`` (an ObjectId) into a string ``id``,
    so nothing MongoDB-specific leaks past this boundary.
    """
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
