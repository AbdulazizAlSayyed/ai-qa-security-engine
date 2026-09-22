"""Persistence layer for the ``evidence`` collection.

The canonical home of normalized evidence. One document per evidence record,
each carrying the ``assessment_id`` it belongs to plus the ``source_run_id``
and ``source_finding_id`` it was derived from, so every record walks back:

    assessment -> evidence -> qa_runs / security_runs -> the tool's finding

Records are compact on purpose. The tools' full output is never copied here;
it stays in ``qa_runs`` and ``security_runs``, the untouched source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "evidence"

BY_ASSESSMENT_INDEX_NAME = "evidence_by_assessment"
BY_ASSESSMENT_INDEX_KEYS = [("assessment_id", ASCENDING), ("timestamp", DESCENDING)]

#: Display order: the order the normalizer emitted (QA suite order, then
#: security most-severe-first). The equality match on ``assessment_id`` uses
#: the index; the per-assessment set is small enough to sort in memory.
LIST_SORT = [("sequence", ASCENDING), ("_id", ASCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the evidence collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the evidence index. Safe to call repeatedly. Non-unique."""
    await get_collection(db).create_index(
        BY_ASSESSMENT_INDEX_KEYS,
        name=BY_ASSESSMENT_INDEX_NAME,
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a stored evidence record into the shape the API exposes."""
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
