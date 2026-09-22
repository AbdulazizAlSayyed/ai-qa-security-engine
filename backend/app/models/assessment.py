"""Persistence layer for the ``assessments`` collection.

An assessment is the unified record of one pipeline pass. It *references*
the QA and security runs by id rather than copying them, and its evidence
lives in the separate ``evidence`` collection keyed by ``assessment_id``.

That split is deliberate. ``qa_runs`` and ``security_runs`` stay the
untouched record of what each tool actually emitted, ``evidence`` holds the
normalized view, and the assessment holds lifecycle, state history, stage
outcomes and deterministic summary counts. Nothing is rewritten in place,
so every claim traces back to the execution that produced it.

The document is written when the assessment is created and updated on every
state transition, so a caller can watch the real state while it runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "assessments"

BY_TARGET_INDEX_NAME = "assessments_by_target"
BY_TARGET_INDEX_KEYS = [("target_id", ASCENDING), ("started_at", DESCENDING)]

LIST_SORT = [("created_at", DESCENDING), ("_id", DESCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the assessments collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the assessment indexes. Safe to call repeatedly. Non-unique."""
    await get_collection(db).create_index(
        BY_TARGET_INDEX_KEYS,
        name=BY_TARGET_INDEX_NAME,
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a stored assessment into the shape the API exposes."""
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
