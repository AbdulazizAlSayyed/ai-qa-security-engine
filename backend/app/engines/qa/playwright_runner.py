"""Browser lifecycle and smoke-suite execution.

Uses Playwright's **synchronous** API, run from a worker thread by the
service layer. The async API would have to share the server's event loop,
which on Windows makes browser subprocess handling fragile and couples the
browser's lifetime to a single HTTP request. A worker thread keeps the event
loop free and leaves the engine callable from a future orchestrator that is
not an HTTP caller at all.

This module never raises. An engine that cannot execute returns a run whose
status is ``error`` with the reason attached, so the caller can persist a
truthful record of what happened instead of losing it in a traceback.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.engines.qa.models import (
    ConsoleError,
    NetworkFailure,
    QaRunOutcome,
    RunStatus,
    TestResult,
    TestStatus,
    derive_run_status,
)
from app.engines.qa.smoke_suite import SMOKE_SUITE, SmokeCheck, SmokeContext

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"

#: How long to let late console/network events arrive before the collection
#: checks report on them.
SETTLE_MS = 750

# Playwright signals application-side problems (timeouts, refused
# connections, navigation aborts) with its own Error type. Those are test
# failures, not engine failures, so they are caught separately below.
try:  # pragma: no cover - depends on whether playwright is installed
    from playwright.sync_api import Error as _PlaywrightError

    _PLAYWRIGHT_ERRORS: tuple[type[BaseException], ...] = (_PlaywrightError,)
except Exception:  # pragma: no cover
    _PLAYWRIGHT_ERRORS = ()


@dataclass(frozen=True)
class BrowserConfig:
    """How to drive the browser for one run."""

    headless: bool = True
    #: "" / None uses Playwright's bundled Chromium; "chrome" or "msedge"
    #: use a locally installed browser instead.
    channel: str | None = None
    navigation_timeout_ms: int = 15_000
    test_timeout_ms: int = 30_000
    #: Phase 9 scoped retest: run only these suite checks (by name). The
    #: first check (reachability) always runs, because it performs the
    #: navigation every other check depends on. None = the whole suite.
    checks: tuple[str, ...] | None = None


def _now() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _playwright_version() -> str:
    try:
        from importlib.metadata import version

        return version("playwright")
    except Exception:  # pragma: no cover
        return "unknown"


def _attach_listeners(
    page: Any,
    console_errors: list[ConsoleError],
    network_failures: list[NetworkFailure],
) -> None:
    """Record console and network problems while the page loads.

    Handlers must never raise - an exception here would surface as a
    confusing engine error rather than the observation it was meant to be.
    """

    def on_console(message: Any) -> None:
        try:
            if message.type != "error":
                return
            location = None
            raw = getattr(message, "location", None)
            if raw:
                location = (
                    f"{raw.get('url', '')}:"
                    f"{raw.get('lineNumber', '')}:{raw.get('columnNumber', '')}"
                )
            console_errors.append(
                ConsoleError(type="console_error", message=message.text, location=location)
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("Could not record a console message", exc_info=True)

    def on_page_error(error: Any) -> None:
        try:
            console_errors.append(
                ConsoleError(type="page_error", message=str(error), location=None)
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("Could not record a page error", exc_info=True)

    def on_request_failed(request: Any) -> None:
        try:
            network_failures.append(
                NetworkFailure(
                    url=request.url,
                    method=request.method,
                    status=None,
                    failure=getattr(request, "failure", None) or "request failed",
                )
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("Could not record a failed request", exc_info=True)

    def on_response(response: Any) -> None:
        try:
            if response.status < 400:
                return
            network_failures.append(
                NetworkFailure(
                    url=response.url,
                    method=response.request.method,
                    status=response.status,
                    failure=None,
                )
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("Could not record an error response", exc_info=True)

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)
    page.on("response", on_response)


def _settle(page: Any, settle_ms: int) -> None:
    """Give in-flight requests and late console output a chance to arrive."""
    try:
        page.wait_for_load_state("load", timeout=settle_ms)
    except Exception:
        pass
    try:
        page.wait_for_timeout(settle_ms)
    except Exception:
        pass


def _run_check(name: str, check: SmokeCheck, ctx: SmokeContext) -> TestResult:
    """Execute one check, timing it and classifying any failure."""
    start = time.perf_counter()

    def build(status: TestStatus, error: str | None, details: dict[str, Any]) -> TestResult:
        return TestResult(
            name=name,
            status=status,
            duration_ms=_elapsed_ms(start),
            url=ctx.final_url,
            title=ctx.title,
            error=error,
            details=details,
        )

    try:
        return build(TestStatus.PASSED, None, check(ctx) or {})
    except AssertionError as exc:
        return build(TestStatus.FAILED, str(exc) or "assertion failed", {})
    except _PLAYWRIGHT_ERRORS as exc:  # type: ignore[misc]
        # The browser reached a verdict about the application: timeout,
        # connection refused, navigation aborted. That is a failing test.
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return build(TestStatus.FAILED, f"{type(exc).__name__}: {message}", {})
    except Exception as exc:
        logger.warning("QA check %r could not execute: %s", name, exc)
        return build(TestStatus.ERROR, f"{type(exc).__name__}: {exc}", {})


def scoped_suite(checks: tuple[str, ...] | None) -> list[tuple[str, SmokeCheck]]:
    """The suite, or only the named checks plus the navigation they depend on."""
    if checks is None:
        return list(SMOKE_SUITE)
    wanted = set(checks)
    return [item for index, item in enumerate(SMOKE_SUITE) if index == 0 or item[0] in wanted]


def _execute_suite(ctx: SmokeContext, checks: tuple[str, ...] | None = None) -> list[TestResult]:
    results: list[TestResult] = []
    settled = False

    for name, check in scoped_suite(checks):
        if not settled and check.__name__.startswith("collect_"):
            _settle(ctx.page, SETTLE_MS)
            settled = True
        results.append(_run_check(name, check, ctx))

    return results


def _close_quietly(*resources: Any) -> None:
    """Close browser resources in order, never masking the original error."""
    for resource in resources:
        if resource is None:
            continue
        try:
            resource.close()
        except Exception:  # pragma: no cover - teardown must not throw
            logger.debug("Error closing %r", type(resource).__name__, exc_info=True)


def run_smoke_suite(base_url: str, config: BrowserConfig | None = None) -> QaRunOutcome:
    """Run the generic smoke suite against ``base_url``.

    Blocking: call it from a worker thread. Returns an outcome in every
    case, including when Playwright is missing or the browser will not
    launch, so the caller always has something truthful to persist.
    """
    config = config or BrowserConfig()
    started_at = _now()
    start = time.perf_counter()

    console_errors: list[ConsoleError] = []
    network_failures: list[NetworkFailure] = []
    tests: list[TestResult] = []
    engine_error: str | None = None

    metadata: dict[str, Any] = {
        "browser": "chromium",
        "channel": config.channel or None,
        "headless": config.headless,
        "engine_version": ENGINE_VERSION,
        "navigation_timeout_ms": config.navigation_timeout_ms,
        "test_timeout_ms": config.test_timeout_ms,
    }
    if config.checks is not None:
        metadata["scoped_checks"] = [name for name, _ in scoped_suite(config.checks)]

    try:
        from playwright.sync_api import sync_playwright

        metadata["playwright_version"] = _playwright_version()

        with sync_playwright() as playwright:
            browser = None
            context = None
            page = None
            try:
                launch_kwargs: dict[str, Any] = {"headless": config.headless}
                if config.channel:
                    launch_kwargs["channel"] = config.channel

                browser = playwright.chromium.launch(**launch_kwargs)
                metadata["browser_version"] = browser.version

                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()
                page.set_default_timeout(config.test_timeout_ms)

                _attach_listeners(page, console_errors, network_failures)

                tests = _execute_suite(
                    SmokeContext(
                        page=page,
                        base_url=base_url,
                        navigation_timeout_ms=config.navigation_timeout_ms,
                        console_errors=console_errors,
                        network_failures=network_failures,
                    ),
                    config.checks,
                )
            finally:
                _close_quietly(page, context, browser)

    except ImportError as exc:
        engine_error = (
            "Playwright is not installed in the backend environment "
            f"({exc}). Install it with: pip install playwright"
        )
        logger.error(engine_error)
    except Exception as exc:
        engine_error = f"{type(exc).__name__}: {exc}"
        logger.exception("QA engine could not execute against %s", base_url)

    finished_at = _now()
    status = RunStatus.ERROR if engine_error else derive_run_status(tests)

    return QaRunOutcome(
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=_elapsed_ms(start),
        tests=tests,
        console_errors=console_errors,
        network_failures=network_failures,
        metadata=metadata,
        error=engine_error,
    )
