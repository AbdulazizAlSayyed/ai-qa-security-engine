"""Application discovery business logic.

    Route -> DiscoveryService -> discovery engine (Playwright)
                  |
                  '-> MongoDB: application_maps

Sits between the HTTP routes and the browser engine. It owns target
validation, the decision to sign in, and persistence; it owns no browser
details and no FastAPI details.

Target lookup reuses :class:`~app.services.target_service.TargetService` so
an unknown or malformed target id behaves identically here and everywhere
else, and account lookup reuses
:class:`~app.services.test_account_service.TestAccountService` so discovery
never queries identities around the registry that owns them.

**Credentials.** This module is the first caller of
:class:`~app.engines.security.credentials.CredentialResolver` in the
platform. A resolved credential lives in memory for the duration of one
crawl, inside the plan handed to the engine, and is never written to the
map, returned by a route, or logged. What is recorded is the account's
*name* and whether the sign-in worked.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Protocol

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.config import Settings
from app.engines.discovery.crawler import (
    DiscoveryConfig,
    FormLoginPlan,
    discover,
)
from app.engines.discovery.models import DiscoveryLimits, DiscoveryOutcome
from app.engines.security.credentials import CredentialError, CredentialResolver
from app.models.application_map import (
    LIST_SORT,
    SUMMARY_PROJECTION,
    document_to_response,
    ensure_indexes,
    get_collection,
)
from app.models.target import AuthMethod, TargetType
from app.schemas.discovery import DiscoveryStartRequest
from app.services.target_service import TargetService
from app.services.test_account_service import TestAccountService

logger = logging.getLogger(__name__)

DEFAULT_RUN_LIMIT = 25


class DiscoveryServiceError(Exception):
    """Base class for discovery failures."""


class InvalidDiscoveryIdError(DiscoveryServiceError):
    """The supplied id is neither an ObjectId nor a discovery id."""


class DiscoveryNotFoundError(DiscoveryServiceError):
    """No discovery run exists with that id on that target."""


class TargetNotDiscoverableError(DiscoveryServiceError):
    """The target exists but cannot legitimately be explored."""


class DiscoveryPersistenceError(DiscoveryServiceError):
    """The run executed but its result could not be stored."""


class DiscoveryEngine(Protocol):
    """What the service needs from the engine.

    Narrow on purpose: tests substitute a fake so most of the suite never
    depends on Chromium being installed, while the real E2E test uses the
    real one.
    """

    def __call__(self, config: DiscoveryConfig) -> DiscoveryOutcome: ...


class DiscoveryService:
    """Runs application discovery against registered targets and stores the maps."""

    #: Discovery drives a browser, so it only means something for a UI target.
    SUPPORTED_TARGET_TYPES: frozenset[str] = frozenset(
        {TargetType.WEB_APPLICATION.value, TargetType.WEB_AND_API.value}
    )

    def __init__(
        self,
        db: AsyncDatabase,
        targets: TargetService,
        accounts: TestAccountService,
        settings: Settings,
        engine: DiscoveryEngine | Callable[..., DiscoveryOutcome] | None = None,
        resolver: CredentialResolver | None = None,
    ) -> None:
        self._db = db
        self._collection = get_collection(db)
        self._targets = targets
        self._accounts = accounts
        self._settings = settings
        self._engine = engine or discover
        self._resolver = resolver or CredentialResolver()

    async def ensure_indexes(self) -> None:
        await ensure_indexes(self._db)

    # --- validation -------------------------------------------------------

    def _require_discoverable(self, target: dict[str, Any]) -> str:
        """Check the target may be explored, and return the URL to start from."""
        name = target.get("name", "target")

        if not target.get("enabled", False):
            raise TargetNotDiscoverableError(
                f"Target {name!r} is disabled. Enable it before running discovery."
            )

        target_type = str(target.get("type", ""))
        if target_type not in self.SUPPORTED_TARGET_TYPES:
            supported = ", ".join(sorted(self.SUPPORTED_TARGET_TYPES))
            raise TargetNotDiscoverableError(
                "Discovery drives a browser, so it needs a web target. Target "
                f"{name!r} has type {target_type!r}; supported types are {supported}."
            )

        base_url = (target.get("base_url") or "").strip()
        if not base_url:
            raise TargetNotDiscoverableError(
                f"Target {name!r} has no base_url, so there is nothing to explore."
            )
        return base_url

    def _limits(self, request: DiscoveryStartRequest) -> DiscoveryLimits:
        """The defaults, lowered by anything the caller asked for.

        A request can only make a crawl smaller. The schema's ceilings stop
        it going the other way, so no request turns discovery into an
        unbounded walk of somebody's application.
        """
        defaults = DiscoveryLimits(
            max_pages=self._settings.discovery_max_pages,
            max_depth=self._settings.discovery_max_depth,
            max_navigations=self._settings.discovery_max_navigations,
            max_duration_seconds=self._settings.discovery_max_duration_seconds,
            stabilize_ms=self._settings.discovery_stabilize_ms,
            navigation_timeout_ms=self._settings.qa_navigation_timeout_ms,
        )

        def lower(requested: int | None, default: int) -> int:
            return default if requested is None else min(requested, default)

        return DiscoveryLimits(
            max_pages=lower(request.max_pages, defaults.max_pages),
            max_depth=lower(request.max_depth, defaults.max_depth),
            max_navigations=defaults.max_navigations,
            max_duration_seconds=lower(
                request.max_duration_seconds, defaults.max_duration_seconds
            ),
            stabilize_ms=defaults.stabilize_ms,
            navigation_timeout_ms=defaults.navigation_timeout_ms,
            max_links_per_page=defaults.max_links_per_page,
            max_elements_per_page=defaults.max_elements_per_page,
            max_forms_per_page=defaults.max_forms_per_page,
        )


    # --- authentication ---------------------------------------------------

    async def _build_login_plan(
        self, target: dict[str, Any], base_url: str
    ) -> tuple[FormLoginPlan | None, str]:
        """Decide whether a sign-in can honestly be attempted, and how.

        Returns the plan, or ``None`` and a reason precise enough to act on.
        Every branch that returns ``None`` names exactly what is missing;
        none of them lets the run report itself as authenticated.
        """
        profile = target.get("authentication") or {}
        policy = target.get("security_policy") or {}
        name = target.get("name", "target")

        if not policy.get("authorized_for_testing"):
            return None, (
                f"Target {name!r} is not marked authorized_for_testing, so no identity "
                "is used. Anonymous discovery ran instead."
            )
        if not policy.get("allow_authenticated_testing"):
            return None, (
                f"Target {name!r} does not have allow_authenticated_testing enabled. "
                "Signing in is authenticated testing, so discovery stayed anonymous."
            )
        if not profile.get("enabled"):
            return None, (
                f"Target {name!r} has no authentication configured "
                "(authentication.enabled is false), so there is nothing to sign in with."
            )

        method = str(profile.get("method") or AuthMethod.NONE.value)
        if method != AuthMethod.FORM_LOGIN.value:
            return None, (
                f"Automated sign-in is implemented for {AuthMethod.FORM_LOGIN.value!r} "
                f"only; this target uses {method!r}. Executing that mode belongs to a "
                "later phase, so discovery ran anonymously rather than pretending to."
            )

        login_url = str(profile.get("login_url") or "").strip()
        username_field = str(profile.get("username_field") or "").strip()
        password_field = str(profile.get("password_field") or "").strip()
        missing = [
            label
            for label, value in (
                ("login_url", login_url),
                ("username_field", username_field),
                ("password_field", password_field),
            )
            if not value
        ]
        if missing:
            return None, (
                "The authentication profile is incomplete: "
                f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set, "
                "so there is no form to fill in."
            )

        try:
            accounts = await self._accounts.list_for_target(target["id"])
        except Exception as exc:  # pragma: no cover - registry failure
            return None, f"The target's test accounts could not be read ({type(exc).__name__})."

        enabled = [account for account in accounts if account.get("enabled")]
        if not enabled:
            return None, (
                "The target has no enabled test account, so there is no identity to "
                "sign in as. Register one and set its credential_reference."
            )

        usable = [account for account in enabled if account.get("credential_available")]
        if not usable:
            names = ", ".join(sorted(str(item.get("name")) for item in enabled))
            return None, (
                f"None of the target's enabled test accounts ({names}) has a resolvable "
                "credential: the environment variable named by credential_reference is "
                "not set on this machine. The platform never stores the value."
            )

        account = usable[0]
        try:
            credential = self._resolver.resolve(account)
        except CredentialError as exc:
            # Names the unset variable; never a value.
            return None, str(exc)

        return (
            FormLoginPlan(
                login_url=login_url if login_url.startswith("http") else
                f"{base_url.rstrip('/')}/{login_url.lstrip('/')}",
                username_field=username_field,
                password_field=password_field,
                credential=credential,
                account_name=str(account.get("name") or ""),
            ),
            "",
        )

    # --- execution --------------------------------------------------------

    async def run(
        self, target_id: str, request: DiscoveryStartRequest | None = None
    ) -> dict[str, Any]:
        """Explore a registered target and store the map it produced.

        A crawl that failed is persisted like any other: a failed discovery
        is a fact about the platform's ability to reach the application, and
        losing it would leave the operator guessing.
        """
        request = request or DiscoveryStartRequest()
        target = await self._targets.get(target_id)
        base_url = self._require_discoverable(target)

        login: FormLoginPlan | None = None
        skip_reason = ""
        if request.authenticated:
            login, skip_reason = await self._build_login_plan(target, base_url)
        else:
            skip_reason = "Anonymous discovery was requested."

        discovery_id = uuid.uuid4().hex
        limits = self._limits(request)

        logger.info(
            "Discovery %s starting: target=%s (%s) url=%s authenticated=%s "
            "max_pages=%d max_depth=%d",
            discovery_id,
            target["id"],
            target.get("name"),
            base_url,
            bool(login),
            limits.max_pages,
            limits.max_depth,
        )

        config = DiscoveryConfig(
            base_url=base_url,
            limits=limits,
            headless=self._settings.qa_headless,
            channel=self._settings.qa_browser_channel or None,
            login=login,
            login_skip_reason=skip_reason,
        )

        # The engine is blocking and drives a browser subprocess, exactly like
        # the QA engine, so it runs on a worker thread.
        outcome = await asyncio.to_thread(self._engine, config)

        document: dict[str, Any] = {
            "target_id": target["id"],
            "target_name": target.get("name", ""),
            "target_base_url": base_url,
            "discovery_id": discovery_id,
            **outcome.to_document(),
        }

        try:
            await self._collection.insert_one(document)
        except DuplicateKeyError as exc:  # pragma: no cover - uuid collision
            raise DiscoveryPersistenceError(
                "A discovery with this id already exists for the target."
            ) from exc
        except PyMongoError as exc:
            raise DiscoveryPersistenceError(
                f"Discovery {discovery_id} finished with status "
                f"{outcome.status.value!r} but could not be stored: {type(exc).__name__}"
            ) from exc

        logger.info(
            "Discovery %s stored: status=%s pages=%d duration=%dms",
            discovery_id,
            outcome.status.value,
            len(outcome.pages),
            outcome.duration_ms,
        )
        return document_to_response(document)

    # --- reads ------------------------------------------------------------

    async def list_for_target(
        self, target_id: str, limit: int = DEFAULT_RUN_LIMIT
    ) -> list[dict[str, Any]]:
        """Recent runs for one target, newest first, without their maps."""
        target = await self._targets.get(target_id)
        try:
            documents = (
                await self._collection.find(
                    {"target_id": target["id"]}, SUMMARY_PROJECTION
                )
                .sort(LIST_SORT)
                .limit(limit)
                .to_list(length=None)
            )
        except PyMongoError as exc:
            raise DiscoveryPersistenceError(
                f"Could not read the discovery runs: {type(exc).__name__}"
            ) from exc
        return [document_to_response(document) for document in documents]

    async def get(self, target_id: str, discovery_id: str) -> dict[str, Any]:
        """One map, addressed by its target and its id.

        The id may be the run's ``discovery_id`` or its ObjectId; both are
        looked up within the target, so a map belonging to another target is
        not found rather than returned.
        """
        target = await self._targets.get(target_id)
        query: dict[str, Any] = {"target_id": target["id"]}
        if ObjectId.is_valid(discovery_id):
            query["$or"] = [
                {"discovery_id": discovery_id},
                {"_id": ObjectId(discovery_id)},
            ]
        else:
            if not discovery_id.strip():
                raise InvalidDiscoveryIdError("A discovery id is required.")
            query["discovery_id"] = discovery_id

        try:
            document = await self._collection.find_one(query)
        except PyMongoError as exc:
            raise DiscoveryPersistenceError(
                f"Could not read the discovery: {type(exc).__name__}"
            ) from exc
        if document is None:
            raise DiscoveryNotFoundError(
                f"No discovery with id {discovery_id} on target {target_id}."
            )
        return document_to_response(document)

    async def latest_map(self, target_id: str) -> dict[str, Any]:
        """The most recent map for a target, whatever its outcome.

        Deliberately not "the most recent successful one": hiding a failed
        run would make a stale map look current.
        """
        target = await self._targets.get(target_id)
        try:
            document = await self._collection.find_one(
                {"target_id": target["id"]}, sort=LIST_SORT
            )
        except PyMongoError as exc:
            raise DiscoveryPersistenceError(
                f"Could not read the application map: {type(exc).__name__}"
            ) from exc
        if document is None:
            raise DiscoveryNotFoundError(
                f"Target {target_id} has no application map yet. Run a discovery first."
            )
        return document_to_response(document)

    async def count_for_target(self, target_id: str) -> int:
        """How many maps a target has. Used by the delete guard."""
        return await self._collection.count_documents({"target_id": target_id})
