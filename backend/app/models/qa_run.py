"""Persistence layer for the ``qa_runs`` collection.

One document per QA execution. The run embeds its test results and
observations rather than splitting them across collections: they are always
read together, they are written once and never updated, and a run is exactly
the unit of evidence that later phases will hand to the AI analyser.

A run also snapshots the target's name and base URL at execution time. If a
target is later renamed or repointed, historical runs must still describe
what was actually tested.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "qa_runs"

#: Runs are browsed newest first, usually filtered to one target.
BY_TARGET_INDEX_NAME = "qa_runs_by_target"
BY_TARGET_INDEX_KEYS = [("target_id", ASCENDING), ("started_at", DESCENDING)]

LIST_SORT = [("started_at", DESCENDING), ("_id", DESCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the QA runs collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the QA run indexes. Safe to call repeatedly.

    Deliberately not unique: re-running QA against the same target is the
    normal case, and every execution is its own record.
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
