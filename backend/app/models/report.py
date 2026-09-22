"""Persistence layer for the ``reports`` collection (Phase 10).

One document per report *generation*. A report is metadata plus references:
the counts and ids of the source records it was assembled from, the
traceability audit result, a small summary, and the location / size /
SHA-256 of the rendered HTML and PDF files under ``REPORTS_ROOT``. Source
collections are never copied here, and neither are raw scanner payloads,
prompts or secrets.

Identity: ``REPORT-###`` per assessment (numbers only grow). Idempotency:
a completed (or in-progress) report is unique on ``dedupe_key`` =
``assessment_id|report_version|source_fingerprint``, so regenerating from
unchanged data returns the existing report instead of a duplicate. Failed
attempts keep their record for auditability but drop the key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "reports"

NUMBER_INDEX_NAME = "reports_by_number"
NUMBER_INDEX_KEYS = [("assessment_id", ASCENDING), ("report_number", DESCENDING)]

DEDUPE_INDEX_NAME = "reports_dedupe"
DEDUPE_INDEX_KEYS = [("dedupe_key", ASCENDING)]

LIST_SORT = [("report_number", DESCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the report indexes. Safe to call repeatedly."""
    collection = get_collection(db)
    await collection.create_index(NUMBER_INDEX_KEYS, name=NUMBER_INDEX_NAME, unique=True)
    await collection.create_index(
        DEDUPE_INDEX_KEYS,
        name=DEDUPE_INDEX_NAME,
        unique=True,
        partialFilterExpression={"dedupe_key": {"$exists": True}},
    )


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    data.pop("dedupe_key", None)
    artifacts = {}
    for name, artifact in (data.get("artifacts") or {}).items():
        # The server-side path stays internal; clients use the download routes.
        artifacts[name] = {k: v for k, v in (artifact or {}).items() if k != "path"}
    data["artifacts"] = artifacts
    return data
