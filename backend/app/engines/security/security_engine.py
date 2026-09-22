"""The security engine: runs every configured scanner and assembles a run.

Deliberately dumb about HTTP and MongoDB, exactly like the QA engine. It is
handed the target's URLs and source path by the service, runs whatever is
configured and applicable, and returns a structured outcome.

Components are independent. ZAP being switched off does not stop the API
probes; a target without an API URL still gets a ZAP scan. That matters
because partial evidence is still evidence, and later phases would rather
have some findings than none.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.engines.security.api_probes import (
    AuthorizationReadiness,
    ProbeConfig,
    authorization_probes_placeholder,
    run_api_probes,
    skipped_api_probes,
)
from app.engines.security.models import (
    ComponentResult,
    ComponentStatus,
    RunStatus,
    SecurityRunOutcome,
    derive_run_status,
)
from app.engines.security.semgrep_runner import SemgrepConfig, run_semgrep
from app.engines.security.zap_runner import ZapConfig, run_zap_baseline

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"


@dataclass(frozen=True)
class SecurityEngineConfig:
    zap: ZapConfig = field(default_factory=ZapConfig)
    probes: ProbeConfig = field(default_factory=ProbeConfig)
    semgrep: SemgrepConfig = field(default_factory=SemgrepConfig)
    api_probes_enabled: bool = True


def _now() -> datetime:
    """UTC at MongoDB's millisecond precision, as the QA engine does."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def run_security_assessment(
    *,
    base_url: str,
    api_url: str | None = None,
    source_path: str | None = None,
    config: SecurityEngineConfig | None = None,
    authorization_readiness: AuthorizationReadiness | None = None,
) -> SecurityRunOutcome:
    """Assess one target with every applicable scanner.

    Blocking; the service calls it from a worker thread. Never raises - an
    engine that cannot execute returns an ``error`` outcome carrying the
    reason, so the caller can persist a truthful record.
    """
    config = config or SecurityEngineConfig()
    started_at = _now()
    start = time.perf_counter()

    components: list[ComponentResult] = []
    engine_metadata: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "scan_profile": "baseline",
        "base_url": base_url,
        "api_url": api_url,
    }
    engine_error: str | None = None

    try:
        # --- OWASP ZAP against the application's UI surface.
        zap_result = run_zap_baseline(base_url, config.zap)
        components.append(zap_result)
        if zap_result.metadata.get("zap_version"):
            engine_metadata["zap_version"] = zap_result.metadata["zap_version"]

        # --- Custom API probes against the registered API surface.
        if not config.api_probes_enabled:
            components.append(
                skipped_api_probes("API probes are disabled in configuration.")
            )
        elif api_url and api_url.strip():
            components.append(run_api_probes(api_url.strip(), config.probes))
        else:
            components.append(
                skipped_api_probes(
                    "The target has no registered api_url, so there was no API to probe."
                )
            )

        # --- Authorization probing: architecture present, never executed.
        #     The readiness summary only shapes the skip reason; no identity
        #     is used and nothing authenticated is attempted.
        components.append(authorization_probes_placeholder(authorization_readiness))

        # --- Optional static analysis.
        semgrep_result = run_semgrep(source_path, config.semgrep)
        components.append(semgrep_result)
        if semgrep_result.metadata.get("semgrep_executable"):
            engine_metadata["semgrep_executable"] = semgrep_result.metadata[
                "semgrep_executable"
            ]

    except Exception as exc:  # pragma: no cover - components already guard themselves
        engine_error = f"{type(exc).__name__}: {exc}"
        logger.exception("Security engine could not execute against %s", base_url)

    finished_at = _now()
    status = RunStatus.ERROR if engine_error else derive_run_status(components)

    engine_metadata["components_run"] = [
        {"name": component.name, "status": component.status.value}
        for component in components
    ]

    outcome = SecurityRunOutcome(
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=int((time.perf_counter() - start) * 1000),
        components=components,
        engine_metadata=engine_metadata,
        error=engine_error,
    )

    logger.info(
        "Security assessment finished: status=%s findings=%s components=%s",
        status.value,
        outcome.summary()["total_findings"],
        ", ".join(f"{c.name}:{c.status.value}" for c in components),
    )
    return outcome


def component_by_name(
    outcome: SecurityRunOutcome, name: str
) -> ComponentResult | None:
    """Convenience lookup used by the service and by tests."""
    for component in outcome.components:
        if component.name == name:
            return component
    return None


__all__ = [
    "ENGINE_VERSION",
    "ComponentStatus",
    "SecurityEngineConfig",
    "component_by_name",
    "run_security_assessment",
]
