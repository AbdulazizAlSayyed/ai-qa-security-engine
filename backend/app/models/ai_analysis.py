"""Persistence layer for the ``ai_analysis_logs`` collection.

One document per analysis *execution*. Re-analysing an assessment adds a new
document; nothing is overwritten, so every result stays attributable to the
provider, model, contract version and evidence set that produced it.

An analysis references evidence by ``evidence_id`` - the evidence itself is
never copied here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "ai_analysis_logs"

BY_ASSESSMENT_INDEX_NAME = "ai_analysis_by_assessment"
BY_ASSESSMENT_INDEX_KEYS = [("assessment_id", ASCENDING), ("created_at", DESCENDING)]

LIST_SORT = [("created_at", DESCENDING), ("_id", DESCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the analysis index. Safe to call repeatedly. Non-unique."""
    await get_collection(db).create_index(
        BY_ASSESSMENT_INDEX_KEYS,
        name=BY_ASSESSMENT_INDEX_NAME,
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Stored document -> API shape. The raw model text stays in the database."""
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    data.pop("raw_response", None)
    return data
