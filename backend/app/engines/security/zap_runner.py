"""OWASP ZAP integration.

ZAP runs as a separate native process (its own JVM) and is driven over its
local REST API. It is never embedded in the FastAPI process, and its
location is entirely configuration-driven - nothing here knows which machine
it is on.

Phase 3 performs a **baseline** assessment only:

1. read ZAP's version, proving the API is really there;
2. ask ZAP to fetch the target URL through itself, so its passive scanner
   sees the traffic;
3. optionally spider the site - crawling with GET requests only;
4. wait for the passive scan queue to drain;
5. read and normalize the resulting alerts.

There is deliberately no active scan. Active scanning sends attack payloads,
and that is not something this engine should do by default against anything.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.engines.security.models import (
    ComponentResult,
    ComponentStatus,
    SecurityFinding,
    Severity,
)

logger = logging.getLogger(__name__)

COMPONENT_NAME = "zap"

#: ZAP's risk vocabulary mapped onto ours. ZAP spells "Informational"
#: several ways depending on version and endpoint.
_RISK_TO_SEVERITY: dict[str, Severity] = {
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
    "informational": Severity.INFORMATIONAL,
    "info": Severity.INFORMATIONAL,
    "": Severity.INFORMATIONAL,
}

#: Keep documents a sane size; a passive scan of a large site can return
#: thousands of instances of the same alert.
MAX_ALERTS = 250


@dataclass(frozen=True)
class ZapConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    #: Not 8080: that port is very commonly taken by something else.
    port: int = 8090
    api_key: str = ""
    #: Whole-component budget, including spidering and passive-scan drain.
    timeout_seconds: float = 180.0
    spider: bool = True
    spider_max_children: int = 10
    poll_interval_seconds: float = 2.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def normalize_zap_alert(alert: dict[str, Any]) -> SecurityFinding:
    """Translate one ZAP alert into the platform's finding shape.

    ZAP's own values are preserved in ``raw`` - normalizing must never throw
    information away, only make it comparable with other scanners.
    """
    risk = str(alert.get("risk", "")).strip().lower()
    # ZAP writes e.g. "Informational" or sometimes "Low (Medium)".
    risk_key = risk.split(" ")[0] if risk else ""
    severity = _RISK_TO_SEVERITY.get(risk_key, Severity.INFORMATIONAL)

    cwe = str(alert.get("cweid", "") or "").strip() or None
    wasc = str(alert.get("wascid", "") or "").strip() or None
    # ZAP uses "0" / "-1" to mean "not mapped".
    if cwe in {"0", "-1"}:
        cwe = None
    if wasc in {"0", "-1"}:
        wasc = None

    return SecurityFinding(
        source="zap",
        rule_id=str(alert.get("pluginId") or alert.get("alertRef") or "") or None,
        name=str(alert.get("alert") or alert.get("name") or "Unnamed ZAP alert"),
        severity=severity,
        description=(alert.get("description") or None),
        confidence=(str(alert.get("confidence")).lower() if alert.get("confidence") else None),
        url=(alert.get("url") or None),
        method=(alert.get("method") or None),
        parameter=(alert.get("param") or None),
        evidence=(alert.get("evidence") or None),
        solution=(alert.get("solution") or None),
        reference=(alert.get("reference") or None),
        cwe=cwe,
        wasc=wasc,
        raw={
            "risk": alert.get("risk"),
            "alertRef": alert.get("alertRef"),
            "pluginId": alert.get("pluginId"),
            "attack": alert.get("attack"),
            "other": alert.get("other"),
        },
    )


class ZapClient:
    """Thin REST wrapper. Only the handful of endpoints Phase 3 needs."""

    def __init__(self, config: ZapConfig, client: Any) -> None:
        self._config = config
        self._client = client

    def _call(self, path: str, **params: Any) -> dict[str, Any]:
        query = {"apikey": self._config.api_key, **params} if self._config.api_key else params
        response = self._client.get(f"{self._config.base_url}{path}", params=query)
        response.raise_for_status()
        return response.json()

    def version(self) -> str:
        return str(self._call("/JSON/core/view/version/").get("version", "unknown"))

    def access_url(self, url: str) -> None:
        self._call("/JSON/core/action/accessUrl/", url=url, followRedirects="true")

    def start_spider(self, url: str, max_children: int) -> str:
        result = self._call(
            "/JSON/spider/action/scan/",
            url=url,
            maxChildren=str(max_children),
            recurse="true",
        )
        return str(result.get("scan", ""))

    def spider_status(self, scan_id: str) -> int:
        return int(self._call("/JSON/spider/view/status/", scanId=scan_id).get("status", 0))

    def stop_spider(self, scan_id: str) -> None:
        self._call("/JSON/spider/action/stop/", scanId=scan_id)

    def records_to_scan(self) -> int:
        value = self._call("/JSON/pscan/view/recordsToScan/").get("recordsToScan", 0)
        return int(value)

    def alerts(self, base_url: str, count: int = MAX_ALERTS) -> list[dict[str, Any]]:
        result = self._call(
            "/JSON/core/view/alerts/", baseurl=base_url, start="0", count=str(count)
        )
        return list(result.get("alerts", []))


def _wait_until(
    check: Any, done: Any, deadline: float, poll_interval: float
) -> tuple[bool, Any]:
    """Poll ``check`` until ``done`` or the deadline passes."""
    last = None
    while time.monotonic() < deadline:
        last = check()
        if done(last):
            return True, last
        time.sleep(poll_interval)
    return False, last


def run_zap_baseline(
    target_url: str, config: ZapConfig | None = None, client: Any = None
) -> ComponentResult:
    """Run a passive/baseline ZAP assessment against ``target_url``.

    Blocking; the service calls it from a worker thread. Never raises: a ZAP
    that is switched off, unreachable or misbehaving is reported as a
    skipped or failed component so the rest of the run still produces value.
    """
    config = config or ZapConfig()
    started = time.perf_counter()
    metadata: dict[str, Any] = {"zap_api": config.base_url, "scan_type": "baseline"}

    if not config.enabled:
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.SKIPPED,
            enabled=False,
            detail="ZAP is disabled in configuration (ZAP_ENABLED=false).",
            metadata=metadata,
        )

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    owns_client = client is None
    try:
        if owns_client:
            import httpx

            client = httpx.Client(timeout=30.0)
    except Exception as exc:  # pragma: no cover - httpx is a hard dependency
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.FAILED,
            duration_ms=elapsed_ms(),
            detail=f"HTTP client unavailable: {exc}",
            metadata=metadata,
        )

    try:
        zap = ZapClient(config, client)
        deadline = time.monotonic() + config.timeout_seconds

        # --- 1. Is ZAP actually there?
        try:
            version = zap.version()
        except Exception as exc:
            return ComponentResult(
                name=COMPONENT_NAME,
                status=ComponentStatus.FAILED,
                duration_ms=elapsed_ms(),
                detail=(
                    f"ZAP API not reachable at {config.base_url} "
                    f"({type(exc).__name__}: {exc}). Start ZAP, correct ZAP_HOST/ZAP_PORT/"
                    "ZAP_API_KEY, or set ZAP_ENABLED=false to skip this component."
                ),
                metadata=metadata,
            )

        metadata["zap_version"] = version
        logger.info("ZAP %s reachable at %s", version, config.base_url)

        # --- 2. Put the target through ZAP so the passive scanner sees it.
        zap.access_url(target_url)

        # --- 3. Spider (GET-only crawling), bounded by config and deadline.
        if config.spider:
            scan_id = zap.start_spider(target_url, config.spider_max_children)
            metadata["spider_scan_id"] = scan_id
            finished, status = _wait_until(
                lambda: zap.spider_status(scan_id),
                lambda value: value >= 100,
                deadline,
                config.poll_interval_seconds,
            )
            metadata["spider_progress"] = status
            metadata["spider_completed"] = finished
            if not finished:
                # Out of budget: stop crawling rather than keep generating
                # traffic, and still collect what passive scanning saw.
                try:
                    zap.stop_spider(scan_id)
                except Exception:
                    logger.debug("Could not stop ZAP spider %s", scan_id, exc_info=True)
        else:
            metadata["spider_completed"] = False
            metadata["spider_skipped_reason"] = "spider disabled in configuration"

        # --- 4. Let the passive scanner finish what it queued.
        drained, remaining = _wait_until(
            zap.records_to_scan,
            lambda value: value == 0,
            deadline,
            config.poll_interval_seconds,
        )
        metadata["passive_scan_drained"] = drained
        metadata["passive_records_remaining"] = remaining

        # --- 5. Collect and normalize.
        raw_alerts = zap.alerts(target_url)
        metadata["alert_count"] = len(raw_alerts)
        metadata["alerts_truncated"] = len(raw_alerts) >= MAX_ALERTS
        findings = [normalize_zap_alert(alert) for alert in raw_alerts]

        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.COMPLETED,
            duration_ms=elapsed_ms(),
            findings=findings,
            metadata=metadata,
        )

    except Exception as exc:
        logger.exception("ZAP baseline failed against %s", target_url)
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.FAILED,
            duration_ms=elapsed_ms(),
            detail=f"{type(exc).__name__}: {exc}",
            metadata=metadata,
        )
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - teardown must not throw
                logger.debug("Error closing ZAP HTTP client", exc_info=True)
