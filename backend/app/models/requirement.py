"""Persistence layer for the ``requirements`` collection.

A *requirement* is a statement of what one registered target is supposed to
do, written or approved by a human. It is the first thing in this platform
that is not derived from a tool run: evidence, findings, issues, recommenda-
tions and retests all describe what *was observed*, and a requirement
describes what *should be true*. Later phases will plan tests against these
statements; nothing in Phase 13 executes anything.

Requirements are scoped to a target and nothing else. ``REQ-001`` on one
target and ``REQ-001`` on another are different requirements, which is why
the uniqueness index leads with ``target_id``. A requirement is never moved
between targets - doing so would silently repoint a statement of intent at
an application it was never written for.

``key_number`` is stored alongside the ``REQ-NNN`` key because sorting and
allocating on an integer is exact, while sorting on the string breaks the
moment a target reaches REQ-1000. The key is the human reference; the number
is how the database orders and extends the series. The series is allocated
from the live maximum, so a gap left by a deletion in the middle is never
filled, and deleting the highest requirement does free its number again -
``RequirementService._next_key_number`` explains why, and the unique index
below is what actually guarantees no two live requirements share a key.

This module owns everything MongoDB-shaped about a requirement. Business
rules live in ``app.services.requirement_service``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pymongo import ASCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

COLLECTION_NAME = "requirements"

#: Human-readable reference, target-scoped and allocated by the service.
KEY_PREFIX = "REQ-"
KEY_PATTERN = re.compile(r"^REQ-\d{3,}$")
#: Width of the zero-padded number. REQ-1000 and beyond simply get wider,
#: which keeps the series unbroken instead of wrapping or restarting.
KEY_DIGITS = 3
#: The first requirement of a target.
FIRST_KEY_NUMBER = 1

#: Stable reference for one acceptance criterion *within* one requirement.
#: Numbered per requirement, so AC-001 exists on every requirement that has
#: any criteria at all and is only meaningful next to its REQ key.
CRITERION_PREFIX = "AC-"
CRITERION_PATTERN = re.compile(r"^AC-\d{3,}$")
CRITERION_DIGITS = 3


def requirement_key(number: int) -> str:
    """``1`` -> ``"REQ-001"``."""
    return f"{KEY_PREFIX}{number:0{KEY_DIGITS}d}"


def criterion_id(number: int) -> str:
    """``1`` -> ``"AC-001"``."""
    return f"{CRITERION_PREFIX}{number:0{CRITERION_DIGITS}d}"


def criterion_number(value: str) -> int | None:
    """The integer inside an ``AC-NNN`` id, or ``None`` if it is not one."""
    if not isinstance(value, str) or not CRITERION_PATTERN.match(value.strip()):
        return None
    return int(value.strip()[len(CRITERION_PREFIX):])


#: One REQ key per target. The same key on two targets is normal; twice on
#: one target would make every later reference ambiguous.
UNIQUE_INDEX_NAME = "uniq_requirement_key"
UNIQUE_INDEX_KEYS = [("target_id", ASCENDING), ("key", ASCENDING)]

#: The three listings the registry actually offers. Each leads with
#: ``target_id`` because a requirement is never read outside its target, and
#: ends with ``key_number`` so the results inside a bucket come back in the
#: same order every time.
STATUS_INDEX_NAME = "requirements_by_target_status"
STATUS_INDEX_KEYS = [
    ("target_id", ASCENDING),
    ("status", ASCENDING),
    ("key_number", ASCENDING),
]

PRIORITY_INDEX_NAME = "requirements_by_target_priority"
PRIORITY_INDEX_KEYS = [
    ("target_id", ASCENDING),
    ("priority", ASCENDING),
    ("key_number", ASCENDING),
]

AREA_INDEX_NAME = "requirements_by_target_area"
AREA_INDEX_KEYS = [
    ("target_id", ASCENDING),
    ("area", ASCENDING),
    ("key_number", ASCENDING),
]

#: REQ-001 first. Unlike every other collection here, a registry reads best
#: in the order it was written rather than newest-first: a requirement list
#: is a document, not a feed.
LIST_SORT = [("key_number", ASCENDING)]


def get_collection(db: AsyncDatabase) -> AsyncCollection:
    """Return the requirements collection from the application database."""
    return db[COLLECTION_NAME]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create the uniqueness and listing indexes. Safe to call repeatedly."""
    collection = get_collection(db)
    await collection.create_index(
        UNIQUE_INDEX_KEYS, unique=True, name=UNIQUE_INDEX_NAME
    )
    await collection.create_index(STATUS_INDEX_KEYS, name=STATUS_INDEX_NAME)
    await collection.create_index(PRIORITY_INDEX_KEYS, name=PRIORITY_INDEX_NAME)
    await collection.create_index(AREA_INDEX_KEYS, name=AREA_INDEX_NAME)


def document_to_response(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a stored document into the shape the API exposes.

    Turns ``_id`` into a string ``id``. Nothing is stripped: a requirement
    holds no secret, and the schema gives it nowhere to put one.
    """
    data = dict(document)
    data["id"] = str(data.pop("_id"))
    return data
