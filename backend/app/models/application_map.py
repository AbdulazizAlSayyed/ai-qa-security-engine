"""Persistence layer for the ``application_maps`` collection.

One document per discovery run. The map embeds its pages, links, forms,
elements and redirects rather than splitting them across collections: they
are written once, never updated, and always read together - a page's forms
are meaningless without the page, and a map is exactly the unit a later
phase will consume.

This is **runtime evidence about an application's structure**, not
configuration. A target's profile says what the operator declared; a map
says what a browser actually found, at one moment, under one identity. The
two are kept apart on purpose, and nothing here writes back to the registry.

A map also snapshots the target's name and base URL, so a target that is
later renamed or repointed still leaves historical maps describing what was
really explored.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "application_maps"

#: Maps are browsed newest first, always within one target.
BY_TARGET_INDEX_NAME = "application_maps_by_target"
BY_TARGET_INDEX_KEYS = [("target_id", ASCENDING), ("started_at", DESCENDING)]

#: ``discovery_id`` is the run's own reference, unique within a target, so a
#: map can be addressed by it without knowing its ObjectId.
IDENTITY_INDEX_NAME = "application_maps_identity"
IDENTITY_INDEX_KEYS = [("target_id", ASCENDING), ("discovery_id", ASCENDING)]

LIST_SORT = [("started_at", DESCENDING), ("_id", DESCENDING)]

#: Fields that make a map large. The list endpoint leaves them out, so
#: browsing runs does not drag every page of every map across the wire.
SUMMARY_PROJECTION: dict[str, int] = {
    "pages": 0,
    "links": 0,
    "redirects": 0,
    "blocked": 0,
}


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the application maps collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the map indexes. Safe to call repeatedly.

    ``by_target`` is deliberately not unique: re-discovering a target is the
    normal case and every run is its own record. ``identity`` is unique,
    because two runs sharing a discovery id would make every later reference
    ambiguous.
    """
    collection = get_collection(db)
    await collection.create_index(BY_TARGET_INDEX_KEYS, name=BY_TARGET_INDEX_NAME)
    await collection.create_index(
        IDENTITY_INDEX_KEYS, name=IDENTITY_INDEX_NAME, unique=True
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a stored map into the shape the API exposes.

    Nothing is stripped, because nothing secret is in it: the engine never
    reads a field's value, a cookie or a header, so a map has no credential
    to remove.
    """
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
