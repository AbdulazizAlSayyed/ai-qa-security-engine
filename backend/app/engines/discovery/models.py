"""The structured facts one discovery run produces.

Plain dataclasses, like the QA engine's: the engine knows about browsers,
not about HTTP or MongoDB, so it returns Python objects and lets the service
decide how to persist and expose them.

What is deliberately *not* here: page HTML, element values, input contents,
cookies, headers and screenshots. An application map is a set of structural
facts about an application - what pages exist, what they link to, what they
ask for - not a copy of it. A field records that it exists, what it is called
and how to find it again; it never records what anyone typed into it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

#: Version of the discovery contract. Bump it when the shape below changes,
#: so a stored map is never ambiguous about what produced it.
DISCOVERY_VERSION = "1.0"


class DiscoveryStatus(str, Enum):
    """Lifecycle of one discovery run.

    ``failed`` is a real outcome, not an exception that got lost: a run that
    could not launch a browser or could not reach the target is recorded as
    failed with the reason, never as an empty success.
    """

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuthenticationState(str, Enum):
    """Which identity a page was seen as."""

    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"


class NavigationKind(str, Enum):
    """How the crawler got to a page.

    ``client_side`` is the interesting one: the URL changed and the document
    was never reloaded, which is what a client-side router does. It is
    observed, not assumed.
    """

    GOTO = "goto"
    CLICK_CLIENT_SIDE = "click_client_side"
    CLICK_FULL_LOAD = "click_full_load"


class ElementKind(str, Enum):
    BUTTON = "button"
    LINK = "link"
    INPUT = "input"
    SELECT = "select"
    TEXTAREA = "textarea"
    CHECKBOX = "checkbox"
    RADIO = "radio"


class SelectorStrategy(str, Enum):
    """How an element's reference was built, best first.

    Recorded so a later phase can tell a stable reference from a brittle one
    rather than discovering the difference at execution time.
    """

    TEST_ID = "test_id"
    ID = "id"
    NAME = "name"
    ROLE_AND_NAME = "role_and_name"
    CSS_PATH = "css_path"


#: Field names and types that carry a secret. Used only to mark a field as
#: sensitive; no value is read from any field, sensitive or not.
_SENSITIVE_PATTERN = re.compile(
    r"pass(word|wd)?|secret|token|api[-_]?key|cvv|cvc|card[-_]?number|ssn|otp|pin",
    re.IGNORECASE,
)
SENSITIVE_INPUT_TYPES = frozenset({"password"})


def is_sensitive_field(name: str, field_id: str, field_type: str, label: str) -> bool:
    """Would a value in this field be a credential?

    Marking is advisory for later phases. It is not what keeps secrets out of
    the map - nothing ever reads a field's value, so there is no value to
    leak whether this returns true or false.
    """
    if (field_type or "").lower() in SENSITIVE_INPUT_TYPES:
        return True
    return any(
        _SENSITIVE_PATTERN.search(candidate or "") for candidate in (name, field_id, label)
    )


@dataclass(frozen=True)
class DiscoveryLimits:
    """The budget one crawl is allowed to spend.

    Every one of these exists so the crawl terminates on an application that
    generates URLs - pagination, filters, calendars, infinite routes. The
    defaults are sized for a local target.
    """

    max_pages: int = 40
    max_depth: int = 3
    max_navigations: int = 120
    max_duration_seconds: int = 180
    #: How long to let a client-rendered page settle before reading the DOM.
    stabilize_ms: int = 600
    navigation_timeout_ms: int = 15_000
    #: Structured facts per page, so one enormous page cannot fill the map.
    max_links_per_page: int = 200
    max_elements_per_page: int = 150
    max_forms_per_page: int = 20

    def to_document(self) -> dict[str, Any]:
        return {
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "max_navigations": self.max_navigations,
            "max_duration_seconds": self.max_duration_seconds,
            "stabilize_ms": self.stabilize_ms,
            "navigation_timeout_ms": self.navigation_timeout_ms,
            "max_links_per_page": self.max_links_per_page,
            "max_elements_per_page": self.max_elements_per_page,
            "max_forms_per_page": self.max_forms_per_page,
        }


@dataclass
class DiscoveredField:
    """One control inside a form. Its shape, never its contents."""

    name: str
    field_id: str
    type: str
    label: str
    placeholder: str
    required: bool
    selector: str
    selector_strategy: SelectorStrategy
    input_mode: str = ""
    autocomplete: str = ""
    sensitive: bool = False

    def to_document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "field_id": self.field_id,
            "type": self.type,
            "label": self.label,
            "placeholder": self.placeholder,
            "required": self.required,
            "selector": self.selector,
            "selector_strategy": self.selector_strategy.value,
            "input_mode": self.input_mode,
            "autocomplete": self.autocomplete,
            "sensitive": self.sensitive,
        }


@dataclass
class DiscoveredForm:
    """A form that exists on a page. It is read, never submitted."""

    page_url: str
    form_id: str
    name: str
    action: str
    method: str
    selector: str
    fields: list[DiscoveredField] = field(default_factory=list)

    @property
    def field_count(self) -> int:
        return len(self.fields)

    def to_document(self) -> dict[str, Any]:
        return {
            "page_url": self.page_url,
            "form_id": self.form_id,
            "name": self.name,
            "action": self.action,
            "method": self.method,
            "selector": self.selector,
            "field_count": self.field_count,
            "fields": [item.to_document() for item in self.fields],
        }


@dataclass
class DiscoveredElement:
    """An interactive control, with a reference stable enough to find again."""

    page_url: str
    kind: ElementKind
    text: str
    element_id: str
    name: str
    selector: str
    selector_strategy: SelectorStrategy
    role: str = ""
    disabled: bool = False
    #: True when this control sits inside a form. A later phase needs to know
    #: that pressing it would submit something; this phase never presses it.
    in_form: bool = False

    def to_document(self) -> dict[str, Any]:
        return {
            "page_url": self.page_url,
            "kind": self.kind.value,
            "text": self.text,
            "element_id": self.element_id,
            "name": self.name,
            "selector": self.selector,
            "selector_strategy": self.selector_strategy.value,
            "role": self.role,
            "disabled": self.disabled,
            "in_form": self.in_form,
        }


@dataclass
class DiscoveredLink:
    """One navigational link found on one page."""

    source_page_url: str
    href: str
    url: str
    path: str
    text: str
    internal: bool
    followed: bool = False
    #: Only set for a link the crawler actually navigated through.
    navigation_kind: NavigationKind | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "source_page_url": self.source_page_url,
            "href": self.href,
            "url": self.url,
            "path": self.path,
            "text": self.text,
            "internal": self.internal,
            "followed": self.followed,
            "navigation_kind": self.navigation_kind.value if self.navigation_kind else None,
        }


@dataclass
class DiscoveredRedirect:
    """A requested address that ended up somewhere else.

    ``authentication_required`` is only ever set from observed behaviour -
    the same address was requested anonymously and landed elsewhere. It is
    never inferred from a path that merely sounds private.
    """

    requested_url: str
    requested_path: str
    final_url: str
    final_path: str
    authentication_state: AuthenticationState
    authentication_required: bool = False
    status: int | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "requested_path": self.requested_path,
            "final_url": self.final_url,
            "final_path": self.final_path,
            "authentication_state": self.authentication_state.value,
            "authentication_required": self.authentication_required,
            "status": self.status,
        }


@dataclass
class DiscoveredPage:
    """One page of the application, as it rendered."""

    url: str
    path: str
    route_template: str
    title: str
    depth: int
    authentication_state: AuthenticationState
    navigation_kind: NavigationKind
    source_page_url: str | None = None
    status: int | None = None
    link_count: int = 0
    form_count: int = 0
    element_count: int = 0
    forms: list[DiscoveredForm] = field(default_factory=list)
    elements: list[DiscoveredElement] = field(default_factory=list)
    #: Set when the page could not be read; the page is still recorded, so a
    #: blocked or broken screen is visible in the map rather than missing.
    error: str | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "path": self.path,
            "route_template": self.route_template,
            "title": self.title,
            "depth": self.depth,
            "authentication_state": self.authentication_state.value,
            "navigation_kind": self.navigation_kind.value,
            "source_page_url": self.source_page_url,
            "status": self.status,
            "link_count": self.link_count,
            "form_count": self.form_count,
            "element_count": self.element_count,
            "forms": [item.to_document() for item in self.forms],
            "elements": [item.to_document() for item in self.elements],
            "error": self.error,
        }


@dataclass
class AuthenticationAttempt:
    """What was tried, and honestly what happened.

    ``attempted=False`` with a reason is the normal answer for a target that
    is not configured for it. It is never reported as authenticated unless a
    sign-in actually ran and was observed to change the page.
    """

    attempted: bool = False
    succeeded: bool = False
    mode: str = "none"
    #: The test account's *name*. Never a username's password, never a value.
    account_name: str = ""
    #: Precise and actionable when nothing was attempted or it did not work.
    reason: str = ""

    @property
    def state(self) -> AuthenticationState:
        return (
            AuthenticationState.AUTHENTICATED
            if self.attempted and self.succeeded
            else AuthenticationState.ANONYMOUS
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "mode": self.mode,
            "account_name": self.account_name,
            "reason": self.reason,
            "state": self.state.value,
        }


@dataclass
class DiscoveryOutcome:
    """Everything one discovery run produced."""

    status: DiscoveryStatus
    base_url: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    limits: DiscoveryLimits
    authentication: AuthenticationAttempt
    pages: list[DiscoveredPage] = field(default_factory=list)
    links: list[DiscoveredLink] = field(default_factory=list)
    redirects: list[DiscoveredRedirect] = field(default_factory=list)
    #: Addresses that were queued but could not be read, with the reason.
    blocked: list[dict[str, Any]] = field(default_factory=list)
    #: What the crawl could not do, in plain words. Never a guess.
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Set only when the engine itself could not execute.
    error: str | None = None

    @property
    def summary(self) -> dict[str, Any]:
        forms = sum(len(page.forms) for page in self.pages)
        elements = sum(len(page.elements) for page in self.pages)
        return {
            "pages": len(self.pages),
            "links": len(self.links),
            "internal_links": sum(1 for link in self.links if link.internal),
            "external_links": sum(1 for link in self.links if not link.internal),
            "forms": forms,
            "fields": sum(
                form.field_count for page in self.pages for form in page.forms
            ),
            "elements": elements,
            "redirects": len(self.redirects),
            "authentication_required_routes": sum(
                1 for item in self.redirects if item.authentication_required
            ),
            "blocked": len(self.blocked),
            "client_side_navigations": sum(
                1
                for page in self.pages
                if page.navigation_kind is NavigationKind.CLICK_CLIENT_SIDE
            ),
            "routes": len({page.route_template for page in self.pages}),
        }

    def to_document(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "base_url": self.base_url,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "discovery_version": DISCOVERY_VERSION,
            "limits": self.limits.to_document(),
            "authentication": self.authentication.to_document(),
            "summary": self.summary,
            "pages": [item.to_document() for item in self.pages],
            "links": [item.to_document() for item in self.links],
            "redirects": [item.to_document() for item in self.redirects],
            "blocked": self.blocked,
            "notes": self.notes,
            "metadata": self.metadata,
            "error": self.error,
        }
