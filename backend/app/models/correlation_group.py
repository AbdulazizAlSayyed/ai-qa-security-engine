"""Persistence layer for the ``correlation_groups`` collection.

Derived data. One document per group of evidence that describes the same
underlying issue, keyed by ``(assessment_id, group_key)`` so processing the
same assessment again updates the same documents instead of adding new ones.
A group references evidence by ``evidence_id``; evidence is never copied.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "correlation_groups"

#: Idempotency: one group per stable key per assessment. Its prefix also
#: serves every lookup by assessment_id.
IDENTITY_INDEX_NAME = "correlation_groups_identity"
IDENTITY_INDEX_KEYS = [("assessment_id", ASCENDING), ("group_key", ASCENDING)]

#: ``CG-###`` references are unique within an assessment; also the list order.
NUMBER_INDEX_NAME = "correlation_groups_by_number"
NUMBER_INDEX_KEYS = [("assessment_id", ASCENDING), ("group_number", ASCENDING)]

LIST_SORT = [("group_number", ASCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the group indexes. Safe to call repeatedly."""
    collection = get_collection(db)
    await collection.create_index(IDENTITY_INDEX_KEYS, name=IDENTITY_INDEX_NAME, unique=True)
    await collection.create_index(NUMBER_INDEX_KEYS, name=NUMBER_INDEX_NAME, unique=True)


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
