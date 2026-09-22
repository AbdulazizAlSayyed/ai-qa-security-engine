"""Persistence layer for the ``issues`` collection.

Derived data: one prioritized issue per correlation group. The source of
truth stays in ``evidence`` (and behind it ``qa_runs`` / ``security_runs``);
an issue only references evidence ids and, where a completed AI analysis
cites them, AI finding ids.

Issues are keyed by ``(assessment_id, group_key)``, so processing an
assessment again updates the same issues - and keeps their ``ISSUE-###``
numbers - instead of creating duplicates.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "issues"

#: Idempotency: one issue per correlation group per assessment.
IDENTITY_INDEX_NAME = "issues_identity"
IDENTITY_INDEX_KEYS = [("assessment_id", ASCENDING), ("group_key", ASCENDING)]

#: ``ISSUE-###`` references are unique within an assessment.
NUMBER_INDEX_NAME = "issues_by_number"
NUMBER_INDEX_KEYS = [("assessment_id", ASCENDING), ("issue_number", ASCENDING)]

#: The default listing: highest priority first (``P1`` sorts before ``P2``),
#: then highest score, then the stable issue number.
PRIORITY_INDEX_NAME = "issues_by_priority"
PRIORITY_INDEX_KEYS = [
    ("assessment_id", ASCENDING),
    ("priority", ASCENDING),
    ("priority_score", DESCENDING),
    ("issue_number", ASCENDING),
]
LIST_SORT = [("priority", ASCENDING), ("priority_score", DESCENDING), ("issue_number", ASCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the issue indexes. Safe to call repeatedly."""
    collection = get_collection(db)
    await collection.create_index(IDENTITY_INDEX_KEYS, name=IDENTITY_INDEX_NAME, unique=True)
    await collection.create_index(NUMBER_INDEX_KEYS, name=NUMBER_INDEX_NAME, unique=True)
    await collection.create_index(PRIORITY_INDEX_KEYS, name=PRIORITY_INDEX_NAME)


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
