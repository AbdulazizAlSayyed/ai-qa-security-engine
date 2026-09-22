"""The generic QA smoke suite.

Every check here works against *any* web application reachable at a URL.
There are deliberately no selectors, page names, credentials, product names
or workflows belonging to a particular target. Target-specific suites are a
later concern; when they arrive they will live under ``test-targets/``, not
in the engine.

A check raises :class:`AssertionError` to report that the *application*
failed, and returns a dict of details to be recorded. Any other exception
means the *check itself* broke, which the runner records as ``error``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.engines.qa.models import ConsoleError, NetworkFailure


@dataclass
class SmokeContext:
    """Everything a check may look at.

    ``console_errors`` and ``network_failures`` are the runner's own lists,
    shared by reference so the collection checks can report on what the
    event listeners gathered while the page was loading.
    """

    page: Any
    base_url: str
    navigation_timeout_ms: int
    console_errors: list[ConsoleError] = field(default_factory=list)
    network_failures: list[NetworkFailure] = field(default_factory=list)

    # Filled in as checks run, so later checks and the runner can reuse them.
    response: Any = None
    final_url: str | None = None
    title: str | None = None


#: A check takes the context and returns details to record.
SmokeCheck = Callable[[SmokeContext], dict[str, Any]]


def check_application_reachability(ctx: SmokeContext) -> dict[str, Any]:
    """Navigate to the target's base URL and confirm it answers.

    ``domcontentloaded`` rather than ``load`` because a single-page app may
    keep long-lived connections open; waiting for full ``load`` would make
    healthy applications look slow or time out.
    """
    response = ctx.page.goto(
        ctx.base_url,
        wait_until="domcontentloaded",
        timeout=ctx.navigation_timeout_ms,
    )

    ctx.response = response
    ctx.final_url = ctx.page.url

    details: dict[str, Any] = {"requested_url": ctx.base_url, "final_url": ctx.page.url}

    if response is None:
        # Same-document navigations legitimately yield no response object.
        details["http_status"] = None
        details["note"] = "navigation completed without a top-level HTTP response"
        return details

    details["http_status"] = response.status
    details["ok"] = response.ok

    if response.status >= 400:
        raise AssertionError(
            f"Navigating to {ctx.base_url} returned HTTP {response.status}"
        )

    return details


def check_page_title(ctx: SmokeContext) -> dict[str, Any]:
    """The page must have a non-empty title.

    Generic on purpose: the expected text is never asserted, only that the
    application bothered to set one.
    """
    title = ctx.page.title()
    ctx.title = title

    if title is None or not title.strip():
        raise AssertionError("Page title is missing or empty")

    return {"title_length": len(title)}


def check_dom_availability(ctx: SmokeContext) -> dict[str, Any]:
    """The document must expose a usable body."""
    body = ctx.page.query_selector("body")
    if body is None:
        raise AssertionError("Document has no <body> element")

    html_length = ctx.page.evaluate("() => document.documentElement.outerHTML.length")
    if not html_length:
        raise AssertionError("Document markup is empty")

    body_text = (ctx.page.inner_text("body") or "").strip()

    # Empty body text is recorded but not failed: a client-rendered app can
    # legitimately still be painting at domcontentloaded.
    return {
        "html_length": html_length,
        "body_text_length": len(body_text),
        "element_count": ctx.page.evaluate("() => document.querySelectorAll('*').length"),
    }


def collect_console_errors(ctx: SmokeContext) -> dict[str, Any]:
    """Report what the console listeners gathered.

    This check passes as long as collection worked. A console error is an
    observation about the target, not a reason to fail the smoke suite - the
    AI analysis phase decides what it means.
    """
    return {
        "count": len(ctx.console_errors),
        "types": sorted({item.type for item in ctx.console_errors}),
    }


def collect_network_failures(ctx: SmokeContext) -> dict[str, Any]:
    """Report what the network listeners gathered. Observational, as above."""
    statuses = sorted({item.status for item in ctx.network_failures if item.status})
    return {"count": len(ctx.network_failures), "statuses": statuses}


#: Ordered suite. Reachability must come first - it performs the navigation
#: every later check depends on.
SMOKE_SUITE: list[tuple[str, SmokeCheck]] = [
    ("Application Reachability", check_application_reachability),
    ("Page Title", check_page_title),
    ("DOM Availability", check_dom_availability),
    ("Console Error Collection", collect_console_errors),
    ("Network Failure Collection", collect_network_failures),
]
