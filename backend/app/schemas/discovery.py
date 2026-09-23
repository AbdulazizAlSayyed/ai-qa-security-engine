"""Request and response schemas for application discovery.

These mirror what the engine produced and the database stored. There is no
field here for a credential, a cookie, a header, an input value or page
HTML - not as a redaction step, but because the engine never collects any of
them, so there is nothing to leave out.

The request schema exists mainly to bound what a caller may ask for: every
limit has a ceiling, so no request can turn discovery into an unbounded
crawl of somebody's application.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: Hard ceilings. A caller may lower a limit, never raise it past these.
MAX_PAGES_CEILING = 200
MAX_DEPTH_CEILING = 6
MAX_DURATION_CEILING_SECONDS = 600


class DiscoveryStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuthenticationState(str, Enum):
    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"


class NavigationKind(str, Enum):
    GOTO = "goto"
    CLICK_CLIENT_SIDE = "click_client_side"
    CLICK_FULL_LOAD = "click_full_load"


class DiscoveryStartRequest(BaseModel):
    """Payload for ``POST /targets/{target_id}/discoveries``.

    Everything is optional: an empty body runs an anonymous discovery with
    the configured defaults, which is the safe case and the common one.
    """

    model_config = ConfigDict(extra="forbid")

    authenticated: bool = Field(
        default=False,
        description=(
            "Attempt a sign-in first, using the target's authentication profile and "
            "one of its enabled test accounts. Skipped with a reason when the target "
            "is not configured for it; never silently reported as authenticated."
        ),
    )
    max_pages: int | None = Field(default=None, ge=1, le=MAX_PAGES_CEILING)
    max_depth: int | None = Field(default=None, ge=0, le=MAX_DEPTH_CEILING)
    max_duration_seconds: int | None = Field(
        default=None, ge=5, le=MAX_DURATION_CEILING_SECONDS
    )


class DiscoveryLimitsView(BaseModel):
    """The budget the crawl was given. Stored so a map says why it stopped."""

    max_pages: int
    max_depth: int
    max_navigations: int
    max_duration_seconds: int
    stabilize_ms: int
    navigation_timeout_ms: int
    max_links_per_page: int
    max_elements_per_page: int
    max_forms_per_page: int


class AuthenticationView(BaseModel):
    """What was attempted and what happened. Never a credential."""

    attempted: bool
    succeeded: bool
    mode: str
    account_name: str = Field(
        default="", description="The test account's name. Never a username's password."
    )
    reason: str
    state: AuthenticationState


class DiscoverySummary(BaseModel):
    """The counts, so a run can be judged without loading the whole map."""

    pages: int
    links: int
    internal_links: int
    external_links: int
    forms: int
    fields: int
    elements: int
    redirects: int
    authentication_required_routes: int
    blocked: int
    client_side_navigations: int
    routes: int


class DiscoveredFieldView(BaseModel):
    """One control's shape. Its value is never read, so it is never here."""

    name: str
    field_id: str
    type: str
    label: str
    placeholder: str
    required: bool
    selector: str
    selector_strategy: str
    input_mode: str
    autocomplete: str
    sensitive: bool


class DiscoveredFormView(BaseModel):
    page_url: str
    form_id: str
    name: str
    action: str
    method: str
    selector: str
    field_count: int
    fields: list[DiscoveredFieldView]


class DiscoveredElementView(BaseModel):
    page_url: str
    kind: str
    text: str
    element_id: str
    name: str
    selector: str
    selector_strategy: str
    role: str
    disabled: bool
    in_form: bool


class DiscoveredLinkView(BaseModel):
    source_page_url: str
    href: str
    url: str
    path: str
    text: str
    internal: bool
    followed: bool
    navigation_kind: NavigationKind | None


class DiscoveredRedirectView(BaseModel):
    requested_url: str
    requested_path: str
    final_url: str
    final_path: str
    authentication_state: AuthenticationState
    authentication_required: bool
    status: int | None


class DiscoveredPageView(BaseModel):
    url: str
    path: str
    route_template: str
    title: str
    depth: int
    authentication_state: AuthenticationState
    navigation_kind: NavigationKind
    source_page_url: str | None
    status: int | None
    link_count: int
    form_count: int
    element_count: int
    forms: list[DiscoveredFormView]
    elements: list[DiscoveredElementView]
    error: str | None


class BlockedAddressView(BaseModel):
    """An address that was queued and could not be read, with the reason."""

    url: str
    path: str
    depth: int
    source_page_url: str | None = None
    reason: str


class DiscoveryRunView(BaseModel):
    """One discovery run without its map. What the list endpoint returns."""

    id: str = Field(description="String form of the MongoDB ObjectId.")
    target_id: str
    target_name: str
    target_base_url: str
    discovery_id: str = Field(description="The run's own reference, unique per target.")
    status: DiscoveryStatus
    base_url: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    discovery_version: str
    limits: DiscoveryLimitsView
    authentication: AuthenticationView
    summary: DiscoverySummary
    notes: list[str]
    metadata: dict[str, Any]
    error: str | None


class ApplicationMapResponse(DiscoveryRunView):
    """One discovery run with everything it found."""

    pages: list[DiscoveredPageView]
    links: list[DiscoveredLinkView]
    redirects: list[DiscoveredRedirectView]
    blocked: list[BlockedAddressView]
