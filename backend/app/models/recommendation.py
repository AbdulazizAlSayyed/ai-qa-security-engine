"""Persistence layer for the ``recommendations`` collection (Phase 8).

Advisory records only. One document per (assessment, source AI analysis,
primary issue): generating again from the same AI analysis updates the same
documents; a newer AI analysis gets its own set, and the older set stays
readable, so recommendations from different analyses are never mixed.

References only - issues, evidence and AI findings are pointed at by id and
never copied in full.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "recommendations"

#: Idempotency: one recommendation per primary issue per source analysis.
IDENTITY_INDEX_NAME = "recommendations_identity"
IDENTITY_INDEX_KEYS = [("assessment_id", ASCENDING), ("ai_analysis_id", ASCENDING), ("issue_id", ASCENDING)]

#: REC-### lookup and the deterministic list order within one set.
NUMBER_INDEX_NAME = "recommendations_by_number"
NUMBER_INDEX_KEYS = [
    ("assessment_id", ASCENDING),
    ("ai_analysis_id", ASCENDING),
    ("recommendation_number", ASCENDING),
]

LIST_SORT = [("recommendation_number", ASCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the recommendation indexes. Safe to call repeatedly."""
    collection = get_collection(db)
    await collection.create_index(IDENTITY_INDEX_KEYS, name=IDENTITY_INDEX_NAME, unique=True)
    await collection.create_index(NUMBER_INDEX_KEYS, name=NUMBER_INDEX_NAME, unique=True)


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
