"""Read access to prioritized issues (Phase 6).

Issues are written only by :class:`~app.services.correlation_service.CorrelationService`.
This service lists and fetches them, always scoped to one assessment, in the
documented deterministic order: priority (P1 first), then score (highest
first), then issue number.
"""

from __future__ import annotations

import re
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.models import issue as issue_model
from app.services.correlation_service import (
    CorrelationPersistenceError,
    CorrelationServiceError,
    read_assessment,
)

DEFAULT_ISSUE_LIMIT = 200
MAX_ISSUE_LIMIT = 500
ISSUE_ID_PATTERN = re.compile(r"^ISSUE-\d{3,}$")


class InvalidIssueIdError(CorrelationServiceError):
    """The issue reference is not of the form ``ISSUE-###`` (400)."""


class IssueNotFoundError(CorrelationServiceError):
    """No such issue in this assessment (404)."""


class IssueService:
    def __init__(self, db: AsyncDatabase) -> None:
        self._db = db
        self._issues = issue_model.get_collection(db)

    async def list_issues(
        self,
        assessment_id: str,
        *,
        issue_type: str | None = None,
        priority: str | None = None,
        limit: int = DEFAULT_ISSUE_LIMIT,
    ) -> list[dict[str, Any]]:
        await read_assessment(self._db, assessment_id)
        query: dict[str, Any] = {"assessment_id": assessment_id}
        if issue_type:
            query["type"] = issue_type
        if priority:
            query["priority"] = priority
        try:
            documents = (
                await self._issues.find(query)
                .sort(issue_model.LIST_SORT)
                .limit(limit)
                .to_list(length=None)
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(f"Could not read issues: {type(exc).__name__}") from exc
        return [issue_model.document_to_response(d) for d in documents]

    async def get_issue(self, assessment_id: str, issue_id: str) -> dict[str, Any]:
        await read_assessment(self._db, assessment_id)
        if not ISSUE_ID_PATTERN.match(issue_id):
            raise InvalidIssueIdError(f"{issue_id!r} is not a valid issue reference (ISSUE-###).")
        try:
            document = await self._issues.find_one(
                {"assessment_id": assessment_id, "issue_id": issue_id}
            )
        except PyMongoError as exc:
            raise CorrelationPersistenceError(f"Could not read the issue: {type(exc).__name__}") from exc
        if document is None:
            raise IssueNotFoundError(f"No issue {issue_id} in assessment {assessment_id}.")
        return issue_model.document_to_response(document)
