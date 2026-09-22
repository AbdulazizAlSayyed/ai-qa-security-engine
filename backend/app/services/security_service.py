"""Security assessment business logic.

Sits between the HTTP routes and the security engine, exactly as
``QaService`` does for QA. It owns target validation, the decision to scan,
and persistence; it owns no scanner details and no FastAPI details.

The authorisation boundary lives here: a caller supplies a **target id**,
never a URL. Everything the engine scans is read from the registry, so this
platform can only ever be pointed at applications someone deliberately
registered.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Protocol

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.engines.security.api_probes import ProbeConfig
from app.engines.security.models import SecurityRunOutcome
from app.engines.security.security_engine import (
    SecurityEngineConfig,
    run_security_assessment,
)
from app.engines.security.semgrep_runner import SemgrepConfig
from app.engines.security.zap_runner import ZapConfig
from app.models.security_run import (
    LIST_SORT,
    document_to_response,
    ensure_indexes,
    get_collection,
)
from app.models.target import TargetType
from app.services.target_service import TargetService

logger = logging.getLogger(__name__)

DEFAULT_RUN_LIMIT = 50


class SecurityServiceError(Exception):
    """Base class for security execution failures."""


class InvalidSecurityRunIdError(SecurityServiceError):
    """The supplied run id is not a well-formed ObjectId."""


class SecurityRunNotFoundError(SecurityServiceError):
    """No security run exists with the supplied id."""


class TargetNotScannableError(SecurityServiceError):
    """The target exists but may not legitimately be scanned."""


class SecurityPersistenceError(SecurityServiceError):
    """The assessment ran but its result could not be stored."""


class SecurityEngine(Protocol):
    """What the service needs from an engine.

    Narrow on purpose: tests substitute a fake so the suite never depends on
    ZAP, Semgrep or a live target.
    """

    def __call__(
        self,
        *,
        base_url: str,
        api_url: str | None,
        source_path: str | None,
        config: SecurityEngineConfig,
    ) -> SecurityRunOutcome: ...


def _to_object_id(run_id: str) -> ObjectId:
    if not ObjectId.is_valid(run_id):
        raise InvalidSecurityRunIdError(f"{run_id!r} is not a valid security run id.")
    return ObjectId(run_id)


class SecurityService:
    """Runs the security engine against registered targets and stores results."""

    #: ZAP drives a browser-facing scan, so a UI surface must exist. A pure
    #: API target is handled in a later phase with an API-only profile.
    SUPPORTED_TARGET_TYPES: frozenset[str] = frozenset(
        {TargetType.WEB_APPLICATION.value, TargetType.WEB_AND_API.value}
    )

    def __init__(
        self,
        db: AsyncDatabase,
        targets: TargetService,
        settings: Settings,
        engine: SecurityEngine | Callable[..., SecurityRunOutcome] | None = None,
    ) -> None:
        self._db = db
        self._collection = get_collection(db)
        self._targets = targets
        self._settings = settings
        self._engine = engine or run_security_assessment

    async def ensure_indexes(self) -> None:
        await ensure_indexes(self._db)

    # --- validation ---------------------------------------------------

    def _require_scannable(self, target: dict[str, Any]) -> str:
        """Check the target may be scanned, and return the URL to scan."""
        name = target.get("name", "target")

        if not self._settings.security_enabled:
            raise TargetNotScannableError(
                "The security engine is disabled in configuration (SECURITY_ENABLED=false)."
            )

        if not target.get("enabled", False):
            raise TargetNotScannableError(
                f"Target {name!r} is disabled. Enable it before running a security scan."
            )

        target_type = str(target.get("type", ""))
        if target_type not in self.SUPPORTED_TARGET_TYPES:
            supported = ", ".join(sorted(self.SUPPORTED_TARGET_TYPES))
            raise TargetNotScannableError(
                f"The security engine needs a web target. Target {name!r} has type "
                f"{target_type!r}; supported types are {supported}."
            )

        base_url = (target.get("base_url") or "").strip()
        if not base_url:
            raise TargetNotScannableError(
                f"Target {name!r} has no base_url, so there is nothing to scan."
            )

        return base_url

    def _engine_config(self, components: frozenset[str] | None = None) -> SecurityEngineConfig:
        """Engine configuration from settings.

        ``components`` (Phase 9 retest) keeps only the named scanners
        (``zap``, ``api_probes``, ``semgrep``) switched on; it can only ever
        narrow what settings allow, never enable something they disable.
        """
        settings = self._settings

        def allowed(name: str, enabled: bool) -> bool:
            return enabled and (components is None or name in components)

        return SecurityEngineConfig(
            zap=ZapConfig(
                enabled=allowed("zap", settings.zap_enabled),
                host=settings.zap_host,
                port=settings.zap_port,
                api_key=settings.zap_api_key,
                timeout_seconds=float(settings.security_timeout_seconds),
                spider=settings.zap_spider,
                spider_max_children=settings.zap_spider_max_children,
            ),
            probes=ProbeConfig(
                timeout_seconds=float(settings.api_probe_timeout_seconds),
                verify_tls=settings.api_probe_verify_tls,
            ),
            semgrep=SemgrepConfig(
                enabled=allowed("semgrep", settings.semgrep_enabled),
                executable=settings.semgrep_executable,
                ruleset=settings.semgrep_ruleset,
                timeout_seconds=float(settings.security_timeout_seconds),
            ),
            api_probes_enabled=allowed("api_probes", settings.api_probes_enabled),
        )

    # --- execution ----------------------------------------------------

    async def run(
        self,
        target_id: str,
        *,
        components: frozenset[str] | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        """Assess a registered target and store the result.

        ``components`` (Phase 9 retest) runs only the named scanners; the
        stored run records it as ``scope``. Without it the behaviour is
        exactly as before: every configured scanner.

        Raises for problems the caller could have avoided (unknown target,
        disabled target). Findings are never errors: a target riddled with
        vulnerabilities produces a stored run and a 201, because that is the
        result this platform exists to produce.
        """
        target = await self._targets.get(target_id)
        base_url = self._require_scannable(target)
        api_url = (target.get("api_url") or "").strip() or None
        source_path = (target.get("source_path") or "").strip() or None

        logger.info(
            "Security run starting: target=%s (%s) base_url=%s api_url=%s",
            target["id"],
            target.get("name"),
            base_url,
            api_url,
        )

        # Blocking scanners driving external processes; keep the loop free.
        outcome = await asyncio.to_thread(
            self._engine,
            base_url=base_url,
            api_url=api_url,
            source_path=source_path,
            config=self._engine_config(components),
        )

        document: dict[str, Any] = {
            "target_id": target["id"],
            "target_name": target.get("name", ""),
            "target_base_url": base_url,
            "target_api_url": api_url,
            "target_type": target.get("type", ""),
            **outcome.to_document(),
        }
        if components is not None:
            document["scope"] = {"purpose": purpose or "scoped", "components": sorted(components)}
            # Say why a scanner did not run, instead of "disabled in configuration".
            # The authorization probes keep their own reason (no credentials).
            for component in document.get("components", []):
                name = component.get("name")
                if (
                    name not in components
                    and name != "authorization_probes"
                    and component.get("status") == "skipped"
                ):
                    component["detail"] = "Not part of this scoped run."

        try:
            result = await self._collection.insert_one(document)
        except PyMongoError as exc:
            raise SecurityPersistenceError(
                f"Security run completed with status {outcome.status.value!r} but could "
                f"not be stored: {type(exc).__name__}: {exc}"
            ) from exc

        logger.info(
            "Security run %s finished: status=%s findings=%s duration=%dms",
            result.inserted_id,
            outcome.status.value,
            outcome.summary()["total_findings"],
            outcome.duration_ms,
        )
        return document_to_response(document)

    # --- retrieval ----------------------------------------------------

    async def list_runs(self, limit: int = DEFAULT_RUN_LIMIT) -> list[dict[str, Any]]:
        """Recent security runs, newest first."""
        documents = (
            await self._collection.find({}).sort(LIST_SORT).limit(limit).to_list(length=None)
        )
        return [document_to_response(document) for document in documents]

    async def get_run(self, run_id: str) -> dict[str, Any]:
        document = await self._collection.find_one({"_id": _to_object_id(run_id)})
        if document is None:
            raise SecurityRunNotFoundError(f"No security run with id {run_id}.")
        return document_to_response(document)
