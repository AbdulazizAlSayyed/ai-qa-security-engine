"""QA execution business logic.

Sits between the HTTP routes and the browser engine. It owns target
validation, the decision to execute, and persistence; it owns no browser
details and no FastAPI details.

Target lookup deliberately reuses :class:`~app.services.target_service.TargetService`
rather than querying ``targets`` again, so the registry stays the single
source of truth and its ``InvalidTargetIdError`` / ``TargetNotFoundError``
continue to map to the same status codes they do everywhere else.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Protocol

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.engines.qa.models import QaRunOutcome
from app.engines.qa.playwright_runner import BrowserConfig, run_smoke_suite
from app.models.qa_run import (
    LIST_SORT,
    document_to_response,
    ensure_indexes,
    get_collection,
)
from app.models.target import TargetType
from app.services.target_service import TargetService

logger = logging.getLogger(__name__)

DEFAULT_RUN_LIMIT = 50


class QaServiceError(Exception):
    """Base class for QA execution failures."""


class InvalidQaRunIdError(QaServiceError):
    """The supplied run id is not a well-formed ObjectId."""


class QaRunNotFoundError(QaServiceError):
    """No QA run exists with the supplied id."""


class TargetNotRunnableError(QaServiceError):
    """The target exists but QA cannot legitimately be run against it."""


class QaPersistenceError(QaServiceError):
    """The run executed but its result could not be stored."""


class QaEngine(Protocol):
    """What the service needs from an engine.

    Narrow on purpose: tests substitute a fake so the suite never depends on
    Chromium being installed.
    """

    def __call__(self, base_url: str, config: BrowserConfig) -> QaRunOutcome: ...


def _to_object_id(run_id: str) -> ObjectId:
    if not ObjectId.is_valid(run_id):
        raise InvalidQaRunIdError(f"{run_id!r} is not a valid QA run id.")
    return ObjectId(run_id)


class QaService:
    """Runs the QA engine against registered targets and stores the results."""

    #: A browser-driven suite only means something for targets that serve a UI.
    SUPPORTED_TARGET_TYPES: frozenset[str] = frozenset(
        {TargetType.WEB_APPLICATION.value, TargetType.WEB_AND_API.value}
    )

    def __init__(
        self,
        db: AsyncDatabase,
        targets: TargetService,
        settings: Settings,
        engine: QaEngine | Callable[..., QaRunOutcome] | None = None,
    ) -> None:
        self._db = db
        self._collection = get_collection(db)
        self._targets = targets
        self._settings = settings
        self._engine = engine or run_smoke_suite

    async def ensure_indexes(self) -> None:
        await ensure_indexes(self._db)

    # --- validation ---------------------------------------------------

    def _require_runnable(self, target: dict[str, Any]) -> str:
        """Check the target may be assessed, and return the URL to open."""
        name = target.get("name", "target")

        if not target.get("enabled", False):
            raise TargetNotRunnableError(
                f"Target {name!r} is disabled. Enable it before running QA."
            )

        target_type = str(target.get("type", ""))
        if target_type not in self.SUPPORTED_TARGET_TYPES:
            supported = ", ".join(sorted(self.SUPPORTED_TARGET_TYPES))
            raise TargetNotRunnableError(
                f"The QA engine drives a browser, so it needs a web target. "
                f"Target {name!r} has type {target_type!r}; supported types are {supported}."
            )

        base_url = (target.get("base_url") or "").strip()
        if not base_url:
            raise TargetNotRunnableError(
                f"Target {name!r} has no base_url, so there is nothing to open."
            )

        return base_url

    def _browser_config(self, checks: tuple[str, ...] | None = None) -> BrowserConfig:
        return BrowserConfig(
            headless=self._settings.qa_headless,
            channel=self._settings.qa_browser_channel or None,
            navigation_timeout_ms=self._settings.qa_navigation_timeout_ms,
            test_timeout_ms=self._settings.qa_test_timeout_ms,
            checks=checks,
        )

    # --- execution ----------------------------------------------------

    async def run(
        self,
        target_id: str,
        *,
        checks: tuple[str, ...] | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        """Execute the smoke suite against a registered target and store it.

        ``checks`` (Phase 9 retest) limits the run to the named suite checks
        plus the navigation they depend on; it is recorded on the stored run
        as ``scope`` together with ``purpose``. Without it the behaviour is
        exactly the full suite, as before.

        Raises for problems the caller could have avoided (unknown target,
        disabled target). A run that executed and merely *failed* is not an
        error: it is persisted and returned like any other result, because a
        failing application is exactly what this platform exists to find.
        """
        target = await self._targets.get(target_id)
        base_url = self._require_runnable(target)

        logger.info(
            "QA run starting: target=%s (%s) url=%s",
            target["id"],
            target.get("name"),
            base_url,
        )

        # The engine is blocking and drives a browser subprocess. Running it
        # on a worker thread keeps the event loop responsive and keeps the
        # engine callable from a non-HTTP caller later.
        outcome = await asyncio.to_thread(self._engine, base_url, self._browser_config(checks))

        document: dict[str, Any] = {
            "target_id": target["id"],
            "target_name": target.get("name", ""),
            "target_base_url": base_url,
            "target_type": target.get("type", ""),
            **outcome.to_document(),
        }
        if checks is not None:
            document["scope"] = {"purpose": purpose or "scoped", "checks": list(checks)}

        try:
            result = await self._collection.insert_one(document)
        except PyMongoError as exc:
            # The run really happened; losing it silently would be worse
            # than telling the caller the platform failed.
            raise QaPersistenceError(
                f"QA run completed with status {outcome.status.value!r} but could not be "
                f"stored: {type(exc).__name__}: {exc}"
            ) from exc

        logger.info(
            "QA run %s finished: status=%s duration=%dms",
            result.inserted_id,
            outcome.status.value,
            outcome.duration_ms,
        )
        return document_to_response(document)

    # --- retrieval ----------------------------------------------------

    async def list_runs(self, limit: int = DEFAULT_RUN_LIMIT) -> list[dict[str, Any]]:
        """Recent runs, newest first.

        Bounded by default because runs accumulate with every execution,
        unlike the target registry.
        """
        documents = (
            await self._collection.find({}).sort(LIST_SORT).limit(limit).to_list(length=None)
        )
        return [document_to_response(document) for document in documents]

    async def get_run(self, run_id: str) -> dict[str, Any]:
        document = await self._collection.find_one({"_id": _to_object_id(run_id)})
        if document is None:
            raise QaRunNotFoundError(f"No QA run with id {run_id}.")
        return document_to_response(document)
