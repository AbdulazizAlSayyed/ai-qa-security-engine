"""What counts as the same page, the same origin and the same route.

Pure functions, no browser and no I/O, because page identity is the one
thing a crawler must get exactly right: too strict and it walks the same
page forever under different spellings, too loose and it silently drops
parts of the application.

The rules, and why:

**Fragments are dropped** - ``/products#reviews`` is the same page as
``/products``. The exception is hash routing (``/#/products``), where the
fragment *is* the route: a fragment beginning with ``/`` is kept, because
the application's routing genuinely depends on it.

**Query strings are kept**, with their parameters sorted. ``?page=2`` is a
different page from ``?page=1`` and collapsing them would hide half an
application; sorting only makes two spellings of the same query compare
equal.

**The trailing slash is dropped** except on the root, and the scheme, host
and default port are canonicalised, so ``http://localhost:3000`` and
``http://localhost:3000/`` are one page rather than two.

**Route templates** (``/products/42`` -> ``/products/:id``) are derived for
grouping and reporting only. They are never used for deduplication: two
products are two pages.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

#: Only these schemes describe a page a browser can be walked through.
#: ``mailto:``, ``tel:``, ``javascript:`` and ``blob:`` are recorded as links
#: where they appear, and never visited.
CRAWLABLE_SCHEMES = frozenset({"http", "https"})

DEFAULT_PORTS = {"http": "80", "https": "443"}

#: Extensions that are downloads rather than pages. Following one would
#: leave the browser on a file, not an application screen.
NON_PAGE_SUFFIXES = (
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z", ".exe", ".dmg", ".msi",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".mp3", ".mp4", ".avi", ".mov", ".webm", ".wav",
    ".css", ".js", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".csv", ".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx",
)

#: Segments that are an identifier rather than part of the route's shape.
_NUMERIC = re.compile(r"^\d+$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_OBJECT_ID = re.compile(r"^[0-9a-f]{24}$", re.IGNORECASE)
_LONG_HEX = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
_SLUG_WITH_ID = re.compile(r"^(?P<slug>[a-z0-9-]*?)-(?P<id>\d{2,})$", re.IGNORECASE)


def absolute_url(href: str, page_url: str) -> str:
    """Resolve a possibly relative ``href`` against the page it was found on."""
    return urljoin(page_url, (href or "").strip())


def scheme_of(url: str) -> str:
    return urlsplit(url).scheme.lower()


def is_crawlable(url: str) -> bool:
    """Is this something a browser can be walked to, rather than downloaded?"""
    parts = urlsplit(url)
    if parts.scheme.lower() not in CRAWLABLE_SCHEMES:
        return False
    if not parts.netloc:
        return False
    path = parts.path.lower()
    return not path.endswith(NON_PAGE_SUFFIXES)


def origin_of(url: str) -> str:
    """``scheme://host[:port]``, with the default port removed."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if port is not None and str(port) != DEFAULT_PORTS.get(scheme, ""):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def is_same_origin(url: str, base_url: str) -> bool:
    """Same scheme, host and port as the target's base URL.

    Deliberately strict. ``localhost`` and ``127.0.0.1`` resolve to the same
    machine but are different origins to a browser, and treating them as one
    would make a crawl's results depend on which spelling was registered.
    """
    return origin_of(url) == origin_of(base_url)


def _canonical_query(query: str) -> str:
    """Sort a query string. Two spellings of one query become one page."""
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode(sorted(pairs), doseq=False)


def _is_hash_route(fragment: str) -> bool:
    """``#/products`` is a route; ``#reviews`` is a position on a page."""
    return fragment.startswith("/")


def normalize_url(url: str, *, keep_hash_route: bool = True) -> str:
    """The canonical spelling of one page's address.

    Two URLs that normalize to the same string are the same page and are
    visited once.
    """
    parts = urlsplit((url or "").strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()

    netloc = host
    if parts.port is not None and str(parts.port) != DEFAULT_PORTS.get(scheme, ""):
        netloc = f"{host}:{parts.port}"

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    fragment = parts.fragment or ""
    if keep_hash_route and _is_hash_route(fragment):
        # Hash routing: the fragment is the route, so it is part of identity.
        # Its own trailing slash is normalised the same way a path's is.
        if len(fragment) > 1 and fragment.endswith("/"):
            fragment = fragment.rstrip("/") or "/"
    else:
        fragment = ""

    return urlunsplit((scheme, netloc, path, _canonical_query(parts.query), fragment))


def path_of(url: str) -> str:
    """The route a page is at, including a hash route when there is one."""
    parts = urlsplit(url)
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    if parts.fragment and _is_hash_route(parts.fragment):
        return f"{path}#{parts.fragment}" if path != "/" else f"#{parts.fragment}"
    return path


def _template_segment(segment: str) -> str:
    if not segment:
        return segment
    if _NUMERIC.match(segment):
        return ":id"
    if _UUID.match(segment) or _OBJECT_ID.match(segment) or _LONG_HEX.match(segment):
        return ":id"
    match = _SLUG_WITH_ID.match(segment)
    if match:
        return f"{match.group('slug')}-:id"
    return segment


def route_template(url: str) -> str:
    """``/products/42`` -> ``/products/:id``.

    Grouping and reporting only: a template never decides whether two pages
    are the same, because two products are genuinely two pages.
    """
    raw = path_of(url)
    prefix = ""
    if raw.startswith("#"):
        prefix, raw = "#", raw[1:]
    elif "#" in raw:
        head, _, tail = raw.partition("#")
        return f"{route_template_path(head)}#{route_template_path(tail)}"
    return prefix + route_template_path(raw)


def route_template_path(path: str) -> str:
    if not path or path == "/":
        return "/"
    segments = path.split("/")
    return "/".join(_template_segment(segment) for segment in segments)


def is_probably_same_page(first: str, second: str) -> bool:
    """Do these two URLs normalize to the same page?"""
    return normalize_url(first) == normalize_url(second)
