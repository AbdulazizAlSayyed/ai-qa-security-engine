"""Persistence layer for the ``security_runs`` collection.

One document per security assessment, following the same shape decisions as
``qa_runs``: components and findings are embedded because they are always
read together, written once and never updated, and a run is the unit of
evidence later phases will hand to the AI analyser.

Runs snapshot the target's name, URLs and type at execution time, so
renaming or repointing a target never rewrites history.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "security_runs"

BY_TARGET_INDEX_NAME = "security_runs_by_target"
BY_TARGET_INDEX_KEYS = [("target_id", ASCENDING), ("started_at", DESCENDING)]

LIST_SORT = [("started_at", DESCENDING), ("_id", DESCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the security runs collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the security run indexes. Safe to call repeatedly.

    Non-unique: repeatedly scanning the same target is the normal case, and
    every execution is its own record.
    """
    await get_collection(db).create_index(
        BY_TARGET_INDEX_KEYS,
        name=BY_TARGET_INDEX_NAME,
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a stored run into the shape the API exposes."""
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
