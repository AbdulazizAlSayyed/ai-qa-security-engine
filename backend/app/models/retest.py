"""Persistence layer for the ``retests`` collection (Phase 9).

One document per retest *execution*: a historical event, never overwritten,
never deleted, never renumbered. ``RETEST-###`` numbers are per assessment
and only ever grow.

A retest references the recommendation, issue, evidence and the new raw
QA / security run by id; it never copies raw runs and never adds evidence
to the original assessment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "retests"

#: RETEST-### lookup, uniqueness of numbers, and chronological history
#: (numbers only grow) per assessment.
NUMBER_INDEX_NAME = "retests_by_number"
NUMBER_INDEX_KEYS = [("assessment_id", ASCENDING), ("retest_number", DESCENDING)]

#: Retest history of one recommendation, newest first.
RECOMMENDATION_INDEX_NAME = "retests_by_recommendation"
RECOMMENDATION_INDEX_KEYS = [
    ("assessment_id", ASCENDING),
    ("recommendation_id", ASCENDING),
    ("retest_number", DESCENDING),
]

#: The execution lock: at most one *running* retest per recommendation
#: document. Partial, so finished retests never collide.
RUNNING_LOCK_INDEX_NAME = "retests_running_lock"
RUNNING_LOCK_INDEX_KEYS = [("recommendation_ref", ASCENDING)]

LIST_SORT = [("retest_number", DESCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the retest indexes. Safe to call repeatedly."""
    collection = get_collection(db)
    await collection.create_index(NUMBER_INDEX_KEYS, name=NUMBER_INDEX_NAME, unique=True)
    await collection.create_index(RECOMMENDATION_INDEX_KEYS, name=RECOMMENDATION_INDEX_NAME)
    await collection.create_index(
        RUNNING_LOCK_INDEX_KEYS,
        name=RUNNING_LOCK_INDEX_NAME,
        unique=True,
        partialFilterExpression={"status": "running"},
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
