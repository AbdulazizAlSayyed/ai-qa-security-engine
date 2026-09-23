"""Phase 14: page identity, origin and route shape.

These are the rules that decide whether a crawl terminates. Too strict and
it walks one page forever under different spellings; too loose and it
silently drops half an application and reports the result as a map. Pure
functions, so they are tested as pure functions - no browser, no database.
"""

from __future__ import annotations

import pytest

from app.engines.discovery.urls import (
    absolute_url,
    is_crawlable,
    is_probably_same_page,
    is_same_origin,
    normalize_url,
    origin_of,
    path_of,
    route_template,
)

BASE = "http://localhost:3000"


# --- normalization ----------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("http://localhost:3000", "http://localhost:3000/"),
        ("http://localhost:3000/products", "http://localhost:3000/products/"),
        ("http://LOCALHOST:3000/products", "http://localhost:3000/products"),
        ("HTTP://localhost:3000/products", "http://localhost:3000/products"),
        ("http://localhost:3000/products#reviews", "http://localhost:3000/products"),
        ("http://localhost:3000/a?b=1&c=2", "http://localhost:3000/a?c=2&b=1"),
        ("http://example.com:80/x", "http://example.com/x"),
        ("https://example.com:443/x", "https://example.com/x"),
    ],
)
def test_two_spellings_of_one_page_are_one_page(first: str, second: str) -> None:
    assert normalize_url(first) == normalize_url(second)
    assert is_probably_same_page(first, second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("http://localhost:3000/a", "http://localhost:3000/b"),
        ("http://localhost:3000/a?page=1", "http://localhost:3000/a?page=2"),
        ("http://localhost:3000/a", "https://localhost:3000/a"),
        ("http://localhost:3000/a", "http://localhost:3001/a"),
    ],
)
def test_genuinely_different_pages_stay_different(first: str, second: str) -> None:
    """A query string that changes what is shown is a different page."""
    assert normalize_url(first) != normalize_url(second)


def test_a_fragment_is_a_position_not_a_page() -> None:
    assert normalize_url("http://localhost:3000/docs#install") == "http://localhost:3000/docs"


def test_a_hash_route_is_part_of_the_page() -> None:
    """``#/products`` is where a hash router puts a route, so it is identity."""
    products = normalize_url("http://localhost:3000/#/products")
    cart = normalize_url("http://localhost:3000/#/cart")
    assert products != cart
    assert products.endswith("#/products")
    assert normalize_url("http://localhost:3000/#/products/") == products


def test_normalization_is_idempotent() -> None:
    once = normalize_url("HTTP://LocalHost:3000/Products/?b=2&a=1#x")
    assert normalize_url(once) == once


# --- origin -----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:3000/",
        "http://localhost:3000/products/42?x=1",
        "http://LOCALHOST:3000/a#b",
    ],
)
def test_same_origin_urls_are_internal(url: str) -> None:
    assert is_same_origin(url, BASE)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:4000/api",
        "https://localhost:3000/",
        "http://127.0.0.1:3000/",
        "https://example.com/",
        "http://evil.example.com/localhost:3000",
    ],
)
def test_other_origins_are_external(url: str) -> None:
    """``127.0.0.1`` is the same machine and a different origin to a browser.

    Treating them as one would make a crawl's reach depend on which spelling
    happened to be registered, which is not a property worth having.
    """
    assert not is_same_origin(url, BASE)


def test_origin_drops_the_default_port() -> None:
    assert origin_of("http://example.com:80/x") == "http://example.com"
    assert origin_of("https://example.com:443/x") == "https://example.com"
    assert origin_of("http://example.com:8080/x") == "http://example.com:8080"


# --- what may be walked to --------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://localhost:3000/", "https://localhost:3000/a/b?c=1"],
)
def test_http_pages_are_crawlable(url: str) -> None:
    assert is_crawlable(url)


@pytest.mark.parametrize(
    "url",
    [
        "mailto:someone@example.com",
        "tel:+15551234",
        "javascript:void(0)",
        "blob:http://localhost:3000/abc",
        "data:text/html,<p>x</p>",
        "http://localhost:3000/report.pdf",
        "http://localhost:3000/bundle.js",
        "http://localhost:3000/logo.svg",
        "http://localhost:3000/export.csv",
    ],
)
def test_non_pages_are_never_walked_to(url: str) -> None:
    """A download is not a screen, and a javascript: href is not a destination."""
    assert not is_crawlable(url)


def test_relative_links_resolve_against_the_page_they_were_found_on() -> None:
    page = "http://localhost:3000/products/42"
    assert absolute_url("/cart", page) == "http://localhost:3000/cart"
    assert absolute_url("../login", page) == "http://localhost:3000/login"
    assert absolute_url("http://other.test/x", page) == "http://other.test/x"


# --- route shape ------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:3000/", "/"),
        ("http://localhost:3000/products", "/products"),
        ("http://localhost:3000/products/42", "/products/:id"),
        ("http://localhost:3000/products/42/reviews", "/products/:id/reviews"),
        (
            "http://localhost:3000/orders/6ab3b9b5695a291c6c8427c9",
            "/orders/:id",
        ),
        (
            "http://localhost:3000/u/3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            "/u/:id",
        ),
        ("http://localhost:3000/blog/hello-world-12", "/blog/hello-world-:id"),
        ("http://localhost:3000/login", "/login"),
    ],
)
def test_identifiers_become_route_parameters(url: str, expected: str) -> None:
    assert route_template(url) == expected


def test_a_template_never_decides_page_identity() -> None:
    """Two products share a route and are still two pages."""
    first = "http://localhost:3000/products/1"
    second = "http://localhost:3000/products/2"
    assert route_template(first) == route_template(second) == "/products/:id"
    assert normalize_url(first) != normalize_url(second)


def test_path_keeps_a_hash_route_and_drops_a_fragment() -> None:
    assert path_of("http://localhost:3000/products?x=1") == "/products"
    assert path_of("http://localhost:3000/products#top") == "/products"
    assert path_of("http://localhost:3000/#/cart") == "#/cart"
