"""Optional Semgrep static analysis.

Semgrep is genuinely optional: a security run must succeed whether or not it
is installed. Every reason not to run it - not installed, disabled, the
target has no registered ``source_path``, the path does not exist - produces
a *skip with a reason*, never a failure.

The source directory comes from the target registry. Nothing here knows any
particular project's layout.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.engines.security.models import (
    ComponentResult,
    ComponentStatus,
    SecurityFinding,
    Severity,
)

logger = logging.getLogger(__name__)

COMPONENT_NAME = "semgrep"

_SEVERITY_MAP: dict[str, Severity] = {
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "info": Severity.INFORMATIONAL,
}

MAX_RESULTS = 250


@dataclass(frozen=True)
class SemgrepConfig:
    enabled: bool = True
    executable: str = "semgrep"
    #: Ruleset identifier passed to --config.
    ruleset: str = "p/security-audit"
    timeout_seconds: float = 180.0


def normalize_semgrep_result(result: dict[str, Any], source_root: str) -> SecurityFinding:
    """Translate one Semgrep result into the platform's finding shape."""
    extra = result.get("extra") or {}
    metadata = extra.get("metadata") or {}

    severity_key = str(extra.get("severity", "")).strip().lower()
    severity = _SEVERITY_MAP.get(severity_key, Severity.INFORMATIONAL)

    cwe_raw = metadata.get("cwe")
    if isinstance(cwe_raw, list):
        cwe = ", ".join(str(item) for item in cwe_raw) or None
    else:
        cwe = str(cwe_raw) if cwe_raw else None

    references = metadata.get("references")
    if isinstance(references, list):
        reference = references[0] if references else None
    else:
        reference = references or None

    path = str(result.get("path", ""))
    line = (result.get("start") or {}).get("line")
    location = f"{path}:{line}" if line else path

    return SecurityFinding(
        source="semgrep",
        rule_id=str(result.get("check_id") or "") or None,
        name=str(result.get("check_id") or "Semgrep finding").split(".")[-1],
        severity=severity,
        description=str(extra.get("message") or "").strip() or None,
        confidence=str(metadata.get("confidence", "")).lower() or None,
        # Static analysis points at code, not a URL.
        url=location,
        evidence=(str(extra.get("lines") or "").strip() or None),
        solution=(str(metadata.get("fix") or "").strip() or None),
        reference=reference,
        cwe=cwe,
        raw={
            "source_root": source_root,
            "path": path,
            "line": line,
            "owasp": metadata.get("owasp"),
            "impact": metadata.get("impact"),
            "semgrep_severity": extra.get("severity"),
        },
    )


def _skip(reason: str, *, enabled: bool = True, **metadata: Any) -> ComponentResult:
    return ComponentResult(
        name=COMPONENT_NAME,
        status=ComponentStatus.SKIPPED,
        enabled=enabled,
        detail=reason,
        metadata=metadata,
    )


def run_semgrep(
    source_path: str | None, config: SemgrepConfig | None = None
) -> ComponentResult:
    """Run Semgrep over a target's registered source tree, if possible.

    Blocking; the service calls it from a worker thread. Never raises.
    """
    config = config or SemgrepConfig()
    started = time.perf_counter()

    if not config.enabled:
        return _skip("Semgrep is disabled in configuration (SEMGREP_ENABLED=false).", enabled=False)

    if not source_path or not str(source_path).strip():
        return _skip(
            "The target has no registered source_path, so there is no code to analyse."
        )

    resolved = Path(str(source_path).strip())
    if not resolved.exists():
        return _skip(
            f"The target's registered source_path does not exist on this machine: {resolved}",
            source_path=str(resolved),
        )

    executable = shutil.which(config.executable)
    if not executable:
        return _skip(
            f"Semgrep is not installed ({config.executable!r} was not found on PATH). "
            "Static analysis is optional; the rest of the scan was unaffected.",
            source_path=str(resolved),
        )

    command = [
        executable,
        "--config",
        config.ruleset,
        "--json",
        "--quiet",
        # Never let Semgrep write anything into the scanned tree.
        "--no-rewrite-rule-ids",
        str(resolved),
    ]

    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.FAILED,
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail=f"Semgrep exceeded its {config.timeout_seconds:.0f}s budget.",
            metadata={"source_path": str(resolved), "ruleset": config.ruleset},
        )
    except Exception as exc:
        logger.exception("Semgrep could not be executed")
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.FAILED,
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail=f"{type(exc).__name__}: {exc}",
            metadata={"source_path": str(resolved), "ruleset": config.ruleset},
        )

    metadata: dict[str, Any] = {
        "source_path": str(resolved),
        "ruleset": config.ruleset,
        "exit_code": completed.returncode,
        "semgrep_executable": executable,
    }

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.FAILED,
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail=(
                "Semgrep produced output that was not valid JSON: "
                f"{(completed.stderr or completed.stdout or '')[:300]}"
            ),
            metadata=metadata,
        )

    results = list(payload.get("results", []))[:MAX_RESULTS]
    metadata["result_count"] = len(payload.get("results", []))
    metadata["results_truncated"] = len(payload.get("results", [])) > MAX_RESULTS
    if payload.get("errors"):
        metadata["semgrep_errors"] = payload["errors"][:5]

    findings = [normalize_semgrep_result(result, str(resolved)) for result in results]

    return ComponentResult(
        name=COMPONENT_NAME,
        status=ComponentStatus.COMPLETED,
        duration_ms=int((time.perf_counter() - started) * 1000),
        findings=findings,
        metadata=metadata,
    )
