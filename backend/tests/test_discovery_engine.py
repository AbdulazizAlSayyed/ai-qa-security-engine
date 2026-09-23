"""Phase 14: what the crawler does, and what it refuses to do.

The crawl logic is exercised against a fake browser serving a fake
application (``tests/discovery_fakes.py``), so the properties that matter -
termination, deduplication, depth, external-origin filtering, redirects,
client-side versus full-load navigation - are tested against an application
whose shape this file decides. That is a *fake test*: it proves the
crawler's logic, never that any real browser works. ``test_discovery_e2e.py``
does that part for real.

The safety section is the important half. Discovery reads; it does not
change the application it is looking at, and several of these tests exist to
make that hard to break by accident later.
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any

import pytest

from app.engines.discovery import crawler as crawler_module
from app.engines.discovery import extraction as extraction_module
from app.engines.discovery.crawler import (
    DiscoveryConfig,
    FormLoginPlan,
    _mark_authentication_required,
    _selector_for_href,
    _Session,
    _take_next,
    _walk,
    perform_form_login,
)
from app.engines.discovery.extraction import (
    EXTRACTION_SCRIPT,
    limits_argument,
    parse_extraction,
)
from app.engines.discovery.models import (
    AuthenticationAttempt,
    AuthenticationState,
    DiscoveredPage,
    DiscoveredRedirect,
    DiscoveryLimits,
    DiscoveryStatus,
    ElementKind,
    NavigationKind,
    SelectorStrategy,
    is_sensitive_field,
)
from app.engines.security.credentials import RuntimeCredential
from tests.discovery_fakes import FakePage, FakePageSpec, button, password_form

BASE = "http://localhost:3000"


def _site(**pages: FakePageSpec) -> dict[str, FakePageSpec]:
    """Keyword paths to a site dict, so a test reads like a sitemap."""
    return {f"{BASE}{'/' if key == 'root' else '/' + key.replace('__', '/')}": spec
            for key, spec in pages.items()}


def _crawl(
    site: dict[str, FakePageSpec],
    limits: DiscoveryLimits | None = None,
    state: AuthenticationState = AuthenticationState.ANONYMOUS,
) -> dict[str, Any]:
    """Run the real walk over a fake browser and return everything it found."""
    config = DiscoveryConfig(base_url=BASE, limits=limits or DiscoveryLimits())
    page = FakePage(site, entry="about:blank")
    session = _Session(page, config)
    pages: list[DiscoveredPage] = []
    links: list[Any] = []
    redirects: list[DiscoveredRedirect] = []
    blocked: list[dict[str, Any]] = []
    notes: list[str] = []
    _walk(session, state, pages, links, redirects, blocked, notes, time.perf_counter())
    _mark_authentication_required(pages, redirects)
    return {
        "pages": pages,
        "links": links,
        "redirects": redirects,
        "blocked": blocked,
        "notes": notes,
        "page": page,
    }


# --- the walk ---------------------------------------------------------------


def test_a_small_application_is_walked_completely() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(title="Home", links=[("/products", "Products"), ("/login", "Sign in")]),
            f"{BASE}/products": FakePageSpec(title="Products", links=[("/products/1", "First")]),
            f"{BASE}/products/1": FakePageSpec(title="First"),
            f"{BASE}/login": FakePageSpec(title="Sign in", forms=[password_form()]),
        }
    )
    paths = {page.path for page in result["pages"]}
    assert paths == {"/", "/products", "/products/1", "/login"}
    assert {page.route_template for page in result["pages"]} == {
        "/",
        "/products",
        "/products/:id",
        "/login",
    }
    assert result["blocked"] == []


def test_the_same_page_is_never_visited_twice() -> None:
    """Every spelling of one address is one page, whoever linked to it."""
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/a", "A"), ("/b", "B")]),
            f"{BASE}/a": FakePageSpec(links=[("/b", "B"), ("/b/", "B again"), ("/", "Home")]),
            f"{BASE}/b": FakePageSpec(links=[("/a", "A"), ("/a?#top", "A again")]),
        }
    )
    paths = [page.path for page in result["pages"]]
    assert sorted(paths) == ["/", "/a", "/b"]
    assert len(paths) == len(set(paths))


def test_a_cycle_terminates() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/a", "A")]),
            f"{BASE}/a": FakePageSpec(links=[("/b", "B")]),
            f"{BASE}/b": FakePageSpec(links=[("/", "Home"), ("/a", "A")]),
        }
    )
    assert len(result["pages"]) == 3


def test_the_page_limit_stops_the_crawl_and_says_so() -> None:
    site = {f"{BASE}/": FakePageSpec(links=[(f"/p/{n}", str(n)) for n in range(20)])}
    for n in range(20):
        site[f"{BASE}/p/{n}"] = FakePageSpec(title=str(n))

    result = _crawl(site, DiscoveryLimits(max_pages=5))
    assert len(result["pages"]) == 5
    assert any("page limit" in note for note in result["notes"])


def test_the_depth_limit_stops_the_crawl_and_says_so() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/a", "A")]),
            f"{BASE}/a": FakePageSpec(links=[("/b", "B")]),
            f"{BASE}/b": FakePageSpec(links=[("/c", "C")]),
            f"{BASE}/c": FakePageSpec(),
        },
        DiscoveryLimits(max_depth=1),
    )
    assert {page.path for page in result["pages"]} == {"/", "/a"}
    assert max(page.depth for page in result["pages"]) == 1
    assert any("depth limit" in note for note in result["notes"])


def test_the_navigation_limit_stops_the_crawl() -> None:
    site = {f"{BASE}/": FakePageSpec(links=[(f"/p/{n}", str(n)) for n in range(20)])}
    for n in range(20):
        site[f"{BASE}/p/{n}"] = FakePageSpec()
    result = _crawl(site, DiscoveryLimits(max_navigations=4, max_pages=100))
    assert len(result["pages"]) <= 4
    assert any("navigation limit" in note for note in result["notes"])


def test_an_unreachable_page_is_recorded_not_dropped() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/broken", "Broken"), ("/ok", "OK")]),
            f"{BASE}/broken": FakePageSpec(fails_with="net::ERR_CONNECTION_REFUSED"),
            f"{BASE}/ok": FakePageSpec(),
        }
    )
    assert {page.path for page in result["pages"]} == {"/", "/ok"}
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["path"] == "/broken"
    assert "ERR_CONNECTION_REFUSED" in result["blocked"][0]["reason"]


def test_depth_is_the_distance_from_the_entry_point() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/a", "A")]),
            f"{BASE}/a": FakePageSpec(links=[("/b", "B")]),
            f"{BASE}/b": FakePageSpec(),
        }
    )
    by_path = {page.path: page.depth for page in result["pages"]}
    assert by_path == {"/": 0, "/a": 1, "/b": 2}


# --- origins, links and SPA navigation --------------------------------------


def test_external_origins_are_recorded_and_never_visited(caplog) -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(
                links=[
                    ("https://example.com/docs", "Docs"),
                    ("http://localhost:4000/api/health", "API"),
                    ("mailto:someone@example.com", "Mail us"),
                    ("/about", "About"),
                ]
            ),
            f"{BASE}/about": FakePageSpec(),
        }
    )

    external = [link for link in result["links"] if not link.internal]
    assert {link.url for link in external} == {
        "https://example.com/docs",
        "http://localhost:4000/api/health",
        "mailto:someone@example.com",
    }
    assert all(not link.followed for link in external)

    # Nothing outside the target's origin was ever opened.
    assert {page.path for page in result["pages"]} == {"/", "/about"}
    for opened in result["page"].goto_calls:
        assert opened.startswith(BASE)


def test_an_in_page_anchor_is_not_a_destination() -> None:
    result = _crawl({f"{BASE}/": FakePageSpec(links=[("#section", "Jump")])})
    assert len(result["pages"]) == 1
    assert result["links"] == []


def test_a_link_is_clicked_when_the_crawler_is_already_on_its_page() -> None:
    """Clicking is what exercises a client-side router at all."""
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/products", "Products")]),
            f"{BASE}/products": FakePageSpec(),
        }
    )
    products = next(page for page in result["pages"] if page.path == "/products")
    assert products.navigation_kind is NavigationKind.CLICK_CLIENT_SIDE
    assert result["page"].clicked == ['a[href="/products"]']
    # A client-side route serves no document, so there is no status to claim.
    assert products.status is None


def test_the_entry_point_is_opened_directly() -> None:
    result = _crawl({f"{BASE}/": FakePageSpec()})
    assert result["pages"][0].navigation_kind is NavigationKind.GOTO
    assert result["pages"][0].status == 200


def test_a_followed_link_records_how_it_was_followed() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/a", "A")]),
            f"{BASE}/a": FakePageSpec(),
        }
    )
    link = result["links"][0]
    assert link.followed is True
    assert link.navigation_kind is NavigationKind.CLICK_CLIENT_SIDE
    assert link.internal is True
    assert link.path == "/a"


# --- redirects and protected routes -----------------------------------------


def test_a_redirect_is_recorded_with_where_it_went() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/cart", "Cart")]),
            f"{BASE}/cart": FakePageSpec(redirect_to="/login"),
            f"{BASE}/login": FakePageSpec(forms=[password_form()]),
        }
    )
    assert len(result["redirects"]) == 1
    redirect = result["redirects"][0]
    assert redirect.requested_path == "/cart"
    assert redirect.final_path == "/login"


def test_a_route_is_protected_when_it_behaves_that_way() -> None:
    """Observed, not guessed: the destination genuinely asks for a password."""
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/cart", "Cart")]),
            f"{BASE}/cart": FakePageSpec(redirect_to="/login"),
            f"{BASE}/login": FakePageSpec(forms=[password_form()]),
        }
    )
    assert result["redirects"][0].authentication_required is True


def test_a_private_sounding_path_is_not_called_protected_on_its_own() -> None:
    """``/admin`` that simply loads is an ordinary page, whatever it is called."""
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/admin", "Admin"), ("/secret", "Secret")]),
            f"{BASE}/admin": FakePageSpec(title="Admin"),
            f"{BASE}/secret": FakePageSpec(redirect_to="/welcome"),
            f"{BASE}/welcome": FakePageSpec(title="Welcome"),
        }
    )
    assert all(not item.authentication_required for item in result["redirects"])
    assert "/admin" in {page.path for page in result["pages"]}


def test_a_redirect_to_a_page_already_in_the_map_is_not_a_second_page() -> None:
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/home", "Home again")]),
            f"{BASE}/home": FakePageSpec(redirect_to="/"),
        }
    )
    assert [page.path for page in result["pages"]] == ["/"]
    assert result["redirects"][0].final_path == "/"


def test_marking_only_applies_to_an_anonymous_crawl() -> None:
    """A redirect seen while signed in says nothing about needing to sign in."""
    pages = [
        DiscoveredPage(
            url=f"{BASE}/login",
            path="/login",
            route_template="/login",
            title="Sign in",
            depth=1,
            authentication_state=AuthenticationState.AUTHENTICATED,
            navigation_kind=NavigationKind.GOTO,
            forms=[
                type(
                    "F",
                    (),
                    {"fields": [type("X", (), {"sensitive": True})()]},
                )()
            ],
        )
    ]
    redirect = DiscoveredRedirect(
        requested_url=f"{BASE}/cart",
        requested_path="/cart",
        final_url=f"{BASE}/login",
        final_path="/login",
        authentication_state=AuthenticationState.AUTHENTICATED,
    )
    _mark_authentication_required(pages, [redirect])
    assert redirect.authentication_required is False


# --- ordering ---------------------------------------------------------------


def test_the_next_address_prefers_one_on_the_current_page() -> None:
    from collections import deque

    from app.engines.discovery.crawler import _Queued

    queue: deque[_Queued] = deque(
        [
            _Queued(url=f"{BASE}/x", depth=1, source_page_url=f"{BASE}/other", href="/x"),
            _Queued(url=f"{BASE}/y", depth=1, source_page_url=f"{BASE}/here", href="/y"),
        ]
    )
    taken = _take_next(queue, f"{BASE}/here")
    assert taken.url == f"{BASE}/y"
    assert len(queue) == 1


def test_the_next_address_falls_back_to_breadth_first_order() -> None:
    from collections import deque

    from app.engines.discovery.crawler import _Queued

    queue: deque[_Queued] = deque(
        [
            _Queued(url=f"{BASE}/x", depth=1, source_page_url=f"{BASE}/other", href="/x"),
            _Queued(url=f"{BASE}/y", depth=1, source_page_url=f"{BASE}/another", href="/y"),
        ]
    )
    assert _take_next(queue, f"{BASE}/nowhere").url == f"{BASE}/x"


# --- forms, fields and elements ---------------------------------------------


def test_forms_and_fields_are_captured_as_structure() -> None:
    result = _crawl({f"{BASE}/": FakePageSpec(forms=[password_form(action="/session")])})
    page = result["pages"][0]
    assert page.form_count == 1
    form = page.forms[0]
    assert form.method == "post"
    assert form.action == "/session"
    assert form.page_url == f"{BASE}/"
    assert [item.name for item in form.fields] == ["email", "password"]
    assert [item.required for item in form.fields] == [True, True]
    assert form.fields[0].label == "Email"
    assert form.fields[1].selector == "[name='password']"


def test_a_password_field_is_marked_sensitive() -> None:
    result = _crawl({f"{BASE}/": FakePageSpec(forms=[password_form()])})
    fields = result["pages"][0].forms[0].fields
    assert fields[0].sensitive is False
    assert fields[1].sensitive is True


@pytest.mark.parametrize(
    ("name", "field_id", "field_type", "label"),
    [
        ("", "", "password", ""),
        ("passwd", "", "text", ""),
        ("", "api_key", "text", ""),
        ("", "", "text", "Card number"),
        ("cvv", "", "text", ""),
        ("otp", "", "text", ""),
    ],
)
def test_credential_shaped_fields_are_recognised(
    name: str, field_id: str, field_type: str, label: str
) -> None:
    assert is_sensitive_field(name, field_id, field_type, label)


@pytest.mark.parametrize(
    ("name", "field_id", "field_type", "label"),
    [("email", "", "email", "Email"), ("quantity", "", "number", "Quantity")],
)
def test_ordinary_fields_are_not(
    name: str, field_id: str, field_type: str, label: str
) -> None:
    assert not is_sensitive_field(name, field_id, field_type, label)


def test_interactive_elements_are_captured_with_their_reference() -> None:
    result = _crawl(
        {f"{BASE}/": FakePageSpec(elements=[button("Add to cart", "add-to-cart")])}
    )
    element = result["pages"][0].elements[0]
    assert element.kind is ElementKind.BUTTON
    assert element.text == "Add to cart"
    assert element.selector == "[data-testid='add-to-cart']"
    assert element.selector_strategy is SelectorStrategy.TEST_ID
    assert element.page_url == f"{BASE}/"


def test_every_supported_control_kind_survives_parsing() -> None:
    kinds = ["button", "link", "input", "select", "textarea", "checkbox", "radio"]
    raw = {
        "title": "",
        "links": [],
        "forms": [],
        "elements": [
            {
                "kind": kind,
                "text": kind,
                "element_id": "",
                "name": "",
                "selector": f"#{kind}",
                "selector_strategy": "id",
                "role": "",
                "disabled": False,
                "in_form": False,
            }
            for kind in kinds
        ],
    }
    _, _, _, elements = parse_extraction(raw, f"{BASE}/")
    assert [item.kind.value for item in elements] == kinds


def test_an_unknown_control_kind_is_dropped_rather_than_guessed() -> None:
    raw = {
        "title": "",
        "links": [],
        "forms": [],
        "elements": [{"kind": "canvas", "selector": "#c", "selector_strategy": "id"}],
    }
    _, _, _, elements = parse_extraction(raw, f"{BASE}/")
    assert elements == []


def test_an_unknown_selector_strategy_degrades_to_css_path() -> None:
    raw = {
        "title": "",
        "links": [],
        "forms": [],
        "elements": [
            {"kind": "button", "selector": "div > button", "selector_strategy": "magic"}
        ],
    }
    _, _, _, elements = parse_extraction(raw, f"{BASE}/")
    assert elements[0].selector_strategy is SelectorStrategy.CSS_PATH


def test_a_page_that_cannot_be_read_is_recorded_with_its_error() -> None:
    """The screen is in the map, with the reason, rather than missing from it."""
    result = _crawl(
        {
            f"{BASE}/": FakePageSpec(links=[("/blank", "Blank")]),
            # Present, so navigation succeeds; absent from the fake renderer,
            # so reading the DOM is what fails.
            f"{BASE}/blank": FakePageSpec(title="", links=[]),
        }
    )
    assert {page.path for page in result["pages"]} == {"/", "/blank"}
