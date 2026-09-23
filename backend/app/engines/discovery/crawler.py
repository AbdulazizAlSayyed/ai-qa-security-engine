"""A bounded breadth-first walk of one application, with a real browser.

Uses Playwright's **synchronous** API, run from a worker thread by the
service layer - the same arrangement the QA engine uses, and for the same
reason: the async API would have to share the server's event loop, which on
Windows makes browser subprocess handling fragile.

This module never raises. A crawl that cannot launch a browser or cannot
reach the target returns an outcome whose status is ``failed`` with the
reason attached, because an empty map reported as a success is a lie about
the application.

**What it does to the target.** It opens pages, reads the rendered DOM, and
clicks links. That is the whole list. It never submits a form, never presses
a button, never sends a request of its own, and never leaves the target's
origin. The single exception is a configured sign-in, which is a deliberate,
recorded act performed once before the walk begins and never repeated.

**How it navigates.** A link is followed by *clicking* it when the crawler
is already on the page that contains it, and by going to its address
otherwise. Clicking is what makes a client-side router work at all, and
comparing the document's load count across the click is what lets the map
say whether a route was client-side or a full page load - observed, not
assumed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any

from app.engines.discovery.extraction import (
    EXTRACTION_SCRIPT,
    limits_argument,
    parse_extraction,
)
from app.engines.discovery.models import (
    AuthenticationAttempt,
    AuthenticationState,
    DISCOVERY_VERSION,
    DiscoveredLink,
    DiscoveredPage,
    DiscoveredRedirect,
    DiscoveryLimits,
    DiscoveryOutcome,
    DiscoveryStatus,
    NavigationKind,
)
from app.engines.discovery.urls import (
    absolute_url,
    is_crawlable,
    is_same_origin,
    normalize_url,
    path_of,
    route_template,
)

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"

try:  # pragma: no cover - depends on whether playwright is installed
    from playwright.sync_api import Error as _PlaywrightError

    _PLAYWRIGHT_ERRORS: tuple[type[BaseException], ...] = (_PlaywrightError,)
except Exception:  # pragma: no cover
    _PLAYWRIGHT_ERRORS = ()


@dataclass(frozen=True)
class FormLoginPlan:
    """Everything needed to sign in once, built by the service from Phase 12.

    The credential is a ``RuntimeCredential`` from
    ``app.engines.security.credentials``, so it renders as ``<redacted>``
    wherever this object is logged or formatted. Nothing in this module
    reads ``credential.password`` except the single ``fill`` call that types
    it into the page.
    """

    login_url: str
    username_field: str
    password_field: str
    credential: Any
    account_name: str

    def __repr__(self) -> str:  # pragma: no cover - trivial, but load-bearing
        return (
            f"FormLoginPlan(login_url={self.login_url!r}, "
            f"account_name={self.account_name!r}, credential=<redacted>)"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class DiscoveryConfig:
    """How to drive one discovery run."""

    base_url: str
    limits: DiscoveryLimits = dataclass_field(default_factory=DiscoveryLimits)
    headless: bool = True
    channel: str | None = None
    #: None means anonymous discovery, which is always available.
    login: FormLoginPlan | None = None
    #: Why authentication is not being attempted, when it is not.
    login_skip_reason: str = ""


@dataclass
class _Queued:
    url: str
    depth: int
    source_page_url: str | None = None
    #: The raw href as written on the source page, so the link can be clicked
    #: rather than navigated to. None for the entry point.
    href: str | None = None
    #: The link record this came from, so following it can be recorded on the
    #: link itself rather than inferred afterwards.
    link: DiscoveredLink | None = None


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


def _selector_for_href(href: str) -> str:
    """A link, addressed exactly as the page wrote it."""
    escaped = href.replace("\\", "\\\\").replace('"', '\\"')
    return f'a[href="{escaped}"]'


def _close_quietly(*resources: Any) -> None:
    for resource in resources:
        if resource is None:
            continue
        try:
            resource.close()
        except Exception:  # pragma: no cover - teardown must not throw
            logger.debug("Error closing %r", type(resource).__name__, exc_info=True)


class _Session:
    """One browser page, plus the bookkeeping a crawl needs around it."""

    def __init__(self, page: Any, config: DiscoveryConfig) -> None:
        self.page = page
        self.config = config
        self.limits = config.limits
        #: Incremented by the document's own load event. A URL change without
        #: an increment is client-side routing.
        self.load_count = 0
        #: Status of the last document response per normalized URL. A
        #: client-side route has none, and that absence is itself truthful.
        self.status_by_url: dict[str, int] = {}
        page.on("load", self._on_load)
        page.on("response", self._on_response)

    def _on_load(self, _: Any) -> None:
        self.load_count += 1

    def _on_response(self, response: Any) -> None:
        try:
            if response.request.resource_type != "document":
                return
            self.status_by_url[normalize_url(response.url)] = int(response.status)
        except Exception:  # pragma: no cover - a listener must never throw
            logger.debug("Could not record a document response", exc_info=True)

    def stabilize(self) -> None:
        """Let a client-rendered page finish rendering, within a bounded wait.

        Two bounded waits rather than one long sleep: the load state usually
        resolves immediately, and the short settle afterwards is what catches
        content a router renders a tick later.
        """
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.limits.stabilize_ms)
        except Exception:
            pass
        try:
            self.page.wait_for_timeout(self.limits.stabilize_ms)
        except Exception:
            pass

    def current_url(self) -> str:
        try:
            return normalize_url(self.page.url)
        except Exception:  # pragma: no cover - defensive
            return ""

    def extract(self) -> dict[str, Any]:
        """Run the one constant script and return its raw answer."""
        return self.page.evaluate(
            EXTRACTION_SCRIPT,
            limits_argument(
                max_links=self.limits.max_links_per_page,
                max_forms=self.limits.max_forms_per_page,
                max_elements=self.limits.max_elements_per_page,
            ),
        )

    # --- navigation ------------------------------------------------------

    def goto(self, url: str) -> NavigationKind:
        self.page.goto(url, timeout=self.limits.navigation_timeout_ms, wait_until="domcontentloaded")
        self.stabilize()
        return NavigationKind.GOTO

    def click_link(self, href: str, expected: str) -> NavigationKind | None:
        """Follow a link by clicking it. Returns None when that did not work.

        Only ``a[href]`` is ever clicked. A button is never pressed, because
        a button can do something, and this phase only looks.
        """
        selector = _selector_for_href(href)
        before_url = self.current_url()
        before_loads = self.load_count
        try:
            locator = self.page.locator(selector).first
            locator.wait_for(state="visible", timeout=self.limits.stabilize_ms)
            locator.click(timeout=self.limits.navigation_timeout_ms, no_wait_after=True)
        except Exception:
            return None

        # A client-side route changes the URL without a navigation event, so
        # wait on the URL itself rather than on a load.
        deadline = time.perf_counter() + (self.limits.navigation_timeout_ms / 1000)
        while time.perf_counter() < deadline:
            if self.current_url() != before_url:
                break
            try:
                self.page.wait_for_timeout(100)
            except Exception:
                return None
        else:
            return None

        if self.current_url() == before_url:
            return None

        self.stabilize()
        if self.current_url() != expected and not self.current_url().startswith(expected):
            # It went somewhere else - a redirect, or the wrong link matched.
            # That is still a real navigation; the caller records where it
            # actually landed.
            pass
        return (
            NavigationKind.CLICK_CLIENT_SIDE
            if self.load_count == before_loads
            else NavigationKind.CLICK_FULL_LOAD
        )


def _reason(exc: BaseException) -> str:
    """One line, naming what went wrong, without a stack trace."""
    text = str(exc).strip().splitlines()
    first = text[0] if text else type(exc).__name__
    return f"{type(exc).__name__}: {first}"[:400]


def perform_form_login(session: _Session, plan: FormLoginPlan) -> AuthenticationAttempt:
    """Sign in once, through the fields Phase 12 recorded.

    This is the only place in the engine that submits anything, and it
    submits exactly one form: the sign-in form the operator configured. The
    password is typed straight from the resolved credential into the page
    and is never assigned, logged, returned or stored.

    Submission is a keypress in the password field rather than a hunt for a
    button, because guessing which control submits a form is how a crawler
    ends up pressing something else.
    """
    username_selector = f'[name="{plan.username_field}"]'
    password_selector = f'[name="{plan.password_field}"]'
    attempt = AuthenticationAttempt(
        attempted=True, mode="form_login", account_name=plan.account_name
    )

    try:
        session.goto(plan.login_url)
    except Exception as exc:
        attempt.reason = f"The login page could not be opened ({_reason(exc)})."
        return attempt

    before_url = session.current_url()

    try:
        session.page.fill(
            username_selector,
            plan.credential.username,
            timeout=session.limits.navigation_timeout_ms,
        )
        session.page.fill(
            password_selector,
            plan.credential.password,
            timeout=session.limits.navigation_timeout_ms,
        )
    except Exception as exc:
        attempt.reason = (
            "The configured username/password fields were not found on the login page "
            f"({username_selector} / {password_selector}). {_reason(exc)}"
        )
        return attempt

    try:
        session.page.press(password_selector, "Enter")
    except Exception as exc:
        attempt.reason = f"The login form could not be submitted ({_reason(exc)})."
        return attempt

    session.stabilize()

    # Success is observed, never assumed: either the page moved on, or the
    # password field it was asking for is gone.
    moved = session.current_url() != before_url
    still_asking = True
    try:
        still_asking = session.page.locator(password_selector).count() > 0
    except Exception:
        still_asking = True

    attempt.succeeded = bool(moved or not still_asking)
    if not attempt.succeeded:
        attempt.reason = (
            "The sign-in form was submitted but the login page is still showing its "
            "password field, so the credential was not accepted. Discovery continued "
            "anonymously."
        )
    return attempt


def _take_next(queue: Any, current_url: str) -> _Queued:
    """The next address to visit, preferring one reachable from where we are.

    Plain breadth-first order would leave the browser on one page while the
    next address came from a different one, so almost every step would have
    to be a fresh page load and the client-side router would never be
    exercised. Taking a link on the *current* page first keeps the walk
    breadth-first in depth - every item still carries the depth it was found
    at - while letting the crawler actually click its way through an
    application the way a person would.
    """
    for index, item in enumerate(queue):
        if item.source_page_url and item.source_page_url == current_url:
            del queue[index]
            return item
    return queue.popleft()


def _walk(
    session: _Session,
    state: AuthenticationState,
    pages: list[DiscoveredPage],
    links: list[DiscoveredLink],
    redirects: list[DiscoveredRedirect],
    blocked: list[dict[str, Any]],
    notes: list[str],
    started: float,
) -> None:
    """Breadth-first over one origin, until a limit says stop."""
    from collections import deque

    limits = session.limits
    base_url = session.config.base_url
    entry = normalize_url(base_url)

    queue: deque[_Queued] = deque([_Queued(url=entry, depth=0)])
    queued: set[str] = {entry}
    visited: set[str] = set()
    navigations = 0
    deadline = started + limits.max_duration_seconds
    depth_capped = False

    while queue:
        if len(pages) >= limits.max_pages:
            notes.append(
                f"Stopped at the page limit ({limits.max_pages}); "
                f"{len(queue)} address(es) were still queued."
            )
            break
        if navigations >= limits.max_navigations:
            notes.append(f"Stopped at the navigation limit ({limits.max_navigations}).")
            break
        if time.perf_counter() > deadline:
            notes.append(
                f"Stopped at the time limit ({limits.max_duration_seconds}s); "
                f"{len(queue)} address(es) were still queued."
            )
            break

        item = _take_next(queue, session.current_url())
        if item.url in visited:
            continue

        kind: NavigationKind | None = None
        # Click the link where we can: it is the only way a client-side
        # router is exercised at all, and how the map learns which routes
        # are client-side.
        if item.href and item.source_page_url and session.current_url() == item.source_page_url:
            kind = session.click_link(item.href, item.url)
        if kind is None:
            try:
                kind = session.goto(item.url)
            except Exception as exc:
                navigations += 1
                blocked.append(
                    {
                        "url": item.url,
                        "path": path_of(item.url),
                        "depth": item.depth,
                        "source_page_url": item.source_page_url,
                        "reason": _reason(exc),
                    }
                )
                continue
        navigations += 1

        final = session.current_url() or item.url
        if final != item.url:
            redirects.append(
                DiscoveredRedirect(
                    requested_url=item.url,
                    requested_path=path_of(item.url),
                    final_url=final,
                    final_path=path_of(final),
                    authentication_state=state,
                    status=session.status_by_url.get(final),
                )
            )

        if item.link is not None:
            item.link.followed = True
            item.link.navigation_kind = kind

        visited.add(item.url)
        if final in visited and final != item.url:
            # The redirect landed on a page already in the map. Recording the
            # redirect is the useful fact; the page itself is not new.
            continue
        visited.add(final)

        try:
            raw = session.extract()
        except Exception as exc:
            pages.append(
                DiscoveredPage(
                    url=final,
                    path=path_of(final),
                    route_template=route_template(final),
                    title="",
                    depth=item.depth,
                    authentication_state=state,
                    navigation_kind=kind,
                    source_page_url=item.source_page_url,
                    status=session.status_by_url.get(final),
                    error=_reason(exc),
                )
            )
            continue

        title, raw_links, forms, elements = parse_extraction(raw, final)

        page_links: list[DiscoveredLink] = []
        for raw_link in raw_links:
            href = raw_link["href"]
            if not href or href.startswith("#"):
                # An in-page anchor is a position, not a destination.
                continue
            absolute = absolute_url(href, final)
            crawlable = is_crawlable(absolute)
            internal = crawlable and is_same_origin(absolute, base_url)
            destination = normalize_url(absolute) if crawlable else absolute
            page_links.append(
                DiscoveredLink(
                    source_page_url=final,
                    href=href,
                    url=destination,
                    path=path_of(destination) if internal else destination,
                    text=raw_link["text"],
                    internal=internal,
                )
            )
        links.extend(page_links)

        pages.append(
            DiscoveredPage(
                url=final,
                path=path_of(final),
                route_template=route_template(final),
                title=title,
                depth=item.depth,
                authentication_state=state,
                navigation_kind=kind,
                source_page_url=item.source_page_url,
                status=session.status_by_url.get(final),
                link_count=len(page_links),
                form_count=len(forms),
                element_count=len(elements),
                forms=forms,
                elements=elements,
            )
        )

        if item.depth >= limits.max_depth:
            depth_capped = True
            continue

        for link in page_links:
            # External origins are recorded and never visited.
            if not link.internal:
                continue
            if link.url in queued or link.url in visited:
                continue
            queued.add(link.url)
            queue.append(
                _Queued(
                    url=link.url,
                    depth=item.depth + 1,
                    source_page_url=final,
                    href=link.href,
                    link=link,
                )
            )

    if depth_capped:
        notes.append(
            f"Links found at depth {limits.max_depth} were not followed "
            "(the depth limit), so the map may be incomplete below it."
        )


def _mark_authentication_required(
    pages: list[DiscoveredPage], redirects: list[DiscoveredRedirect]
) -> None:
    """Derive "this route needs signing in" from what actually happened.

    A redirect only counts when the page it landed on genuinely asks for a
    password. A path is never called protected because its name sounds
    private, and a redirect to an ordinary page is recorded as a redirect and
    nothing more.
    """
    sign_in_pages = {
        page.url
        for page in pages
        if any(item.sensitive for form in page.forms for item in form.fields)
    }
    for redirect in redirects:
        if redirect.authentication_state is not AuthenticationState.ANONYMOUS:
            continue
        if redirect.final_url == redirect.requested_url:
            continue
        if redirect.final_url in sign_in_pages:
            redirect.authentication_required = True


def discover(config: DiscoveryConfig) -> DiscoveryOutcome:
    """Walk one application and return what is actually there.

    Blocking: call it from a worker thread. Returns an outcome in every case,
    including when Playwright is missing, the browser will not launch or the
    target is not running, so the caller always has something truthful to
    persist. An empty map is a ``failed`` run with a reason, never a success.
    """
    started_at = _now()
    start = time.perf_counter()
    limits = config.limits

    pages: list[DiscoveredPage] = []
    links: list[DiscoveredLink] = []
    redirects: list[DiscoveredRedirect] = []
    blocked: list[dict[str, Any]] = []
    notes: list[str] = []
    engine_error: str | None = None

    authentication = AuthenticationAttempt(
        reason=config.login_skip_reason
        or "No authentication was requested; this is an anonymous discovery."
    )

    metadata: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "discovery_version": DISCOVERY_VERSION,
        "browser": "chromium",
        "channel": config.channel or None,
        "headless": config.headless,
    }

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
                page.set_default_timeout(limits.navigation_timeout_ms)

                session = _Session(page, config)

                if config.login is not None:
                    authentication = perform_form_login(session, config.login)
                    if not authentication.succeeded:
                        notes.append(
                            "Authenticated discovery was attempted and did not succeed, "
                            "so the map below is anonymous."
                        )

                _walk(
                    session,
                    authentication.state,
                    pages,
                    links,
                    redirects,
                    blocked,
                    notes,
                    start,
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
        engine_error = _reason(exc)
        logger.exception("Discovery could not execute against %s", config.base_url)

    _mark_authentication_required(pages, redirects)

    if engine_error:
        status = DiscoveryStatus.FAILED
    elif not pages:
        status = DiscoveryStatus.FAILED
        first = blocked[0]["reason"] if blocked else "the target returned nothing readable"
        engine_error = (
            f"No page of {config.base_url} could be read, so there is no application "
            f"map to store. First failure: {first}"
        )
    else:
        status = DiscoveryStatus.COMPLETED

    finished_at = _now()
    outcome = DiscoveryOutcome(
        status=status,
        base_url=config.base_url,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=_elapsed_ms(start),
        limits=limits,
        authentication=authentication,
        pages=pages,
        links=links,
        redirects=redirects,
        blocked=blocked,
        notes=notes,
        metadata=metadata,
        error=engine_error,
    )

    logger.info(
        "Discovery finished: status=%s base_url=%s pages=%d links=%d forms=%d "
        "elements=%d duration=%dms",
        status.value,
        config.base_url,
        len(pages),
        len(links),
        outcome.summary["forms"],
        outcome.summary["elements"],
        outcome.duration_ms,
    )
    return outcome
