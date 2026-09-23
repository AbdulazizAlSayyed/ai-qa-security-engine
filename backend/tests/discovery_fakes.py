"""A fake browser serving a fake application (not collected by pytest).

Driving real Chromium in every unit test would make the suite slow and
flaky, and would test Playwright rather than the crawler. These doubles
implement exactly the slice of the Playwright page API the crawler uses, so
the crawl logic - breadth-first order, deduplication, depth and page limits,
redirects, external-origin filtering, click-versus-load navigation - is
exercised against a known application whose shape the test decides.

The real engine is still exercised for real: ``test_discovery_e2e.py`` runs
it against a live target with a live browser. A fake test never counts as a
real verification of anything, and this file must not blur that line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urljoin

from app.engines.discovery.urls import normalize_url


@dataclass
class FakePageSpec:
    """One page of the fake application."""

    title: str = "Fake"
    #: ``(href, text)`` exactly as the page would write them.
    links: list[tuple[str, str]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    elements: list[dict[str, Any]] = field(default_factory=list)
    #: Where a request for this address actually ends up.
    redirect_to: str | None = None
    status: int = 200
    #: Raise on navigation, the way an unreachable page does.
    fails_with: str | None = None


def password_form(action: str = "/session") -> dict[str, Any]:
    """A sign-in form, so a test can make a page genuinely look protected."""
    return {
        "form_id": "login",
        "name": "login",
        "action": action,
        "method": "post",
        "selector": "[data-testid='login-form']",
        "fields": [
            {
                "name": "email",
                "field_id": "email",
                "type": "email",
                "label": "Email",
                "placeholder": "",
                "required": True,
                "selector": "[name='email']",
                "selector_strategy": "name",
                "input_mode": "email",
                "autocomplete": "username",
            },
            {
                "name": "password",
                "field_id": "password",
                "type": "password",
                "label": "Password",
                "placeholder": "",
                "required": True,
                "selector": "[name='password']",
                "selector_strategy": "name",
                "input_mode": "",
                "autocomplete": "current-password",
            },
        ],
    }


def button(text: str, testid: str) -> dict[str, Any]:
    return {
        "kind": "button",
        "text": text,
        "element_id": "",
        "name": "",
        "selector": f"[data-testid='{testid}']",
        "selector_strategy": "test_id",
        "role": "button",
        "disabled": False,
        "in_form": False,
    }


class FakeLocator:
    """The two things the crawler asks a locator to do."""

    def __init__(self, page: "FakePage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "FakeLocator":
        return self

    def wait_for(self, **_: Any) -> None:
        if self._selector not in self._page.clickable:
            raise RuntimeError(f"no element matches {self._selector}")

    def click(self, **_: Any) -> None:
        self._page.clicked.append(self._selector)
        destination = self._page.clickable.get(self._selector)
        if destination is None:
            raise RuntimeError(f"no element matches {self._selector}")
        # A client-side router changes the address without reloading, which
        # is exactly what makes this worth distinguishing.
        self._page.navigate(destination, full_load=False)

    def count(self) -> int:
        return 1 if self._selector in self._page.clickable else 0


class FakePage:
    """The slice of Playwright's page API the crawler actually uses."""

    def __init__(self, site: dict[str, FakePageSpec], entry: str) -> None:
        self.site = {normalize_url(key): value for key, value in site.items()}
        self.url = entry
        self.clicked: list[str] = []
        self.evaluated: list[tuple[str, Any]] = []
        self.filled: list[tuple[str, str]] = []
        self.pressed: list[tuple[str, str]] = []
        self.goto_calls: list[str] = []
        self.clickable: dict[str, str] = {}
        self._handlers: dict[str, list[Callable[[Any], None]]] = {}

    # --- wiring the crawler uses ----------------------------------------

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def set_default_timeout(self, _: int) -> None:
        pass

    def wait_for_load_state(self, *_: Any, **__: Any) -> None:
        pass

    def wait_for_timeout(self, *_: Any, **__: Any) -> None:
        pass

    # --- navigation -----------------------------------------------------

    def _spec(self, url: str) -> FakePageSpec | None:
        return self.site.get(normalize_url(url))

    def navigate(self, url: str, *, full_load: bool) -> None:
        absolute = urljoin(self.url, url)
        spec = self._spec(absolute)
        if spec is not None and spec.fails_with:
            raise RuntimeError(spec.fails_with)
        if spec is not None and spec.redirect_to:
            absolute = urljoin(absolute, spec.redirect_to)
            spec = self._spec(absolute)
        self.url = normalize_url(absolute)
        if full_load:
            for handler in self._handlers.get("load", []):
                handler(self)
            if spec is not None:
                for handler in self._handlers.get("response", []):
                    handler(_FakeResponse(self.url, spec.status))
        self._refresh_clickable()

    def goto(self, url: str, **_: Any) -> None:
        self.goto_calls.append(url)
        self.navigate(url, full_load=True)

    def _refresh_clickable(self) -> None:
        spec = self._spec(self.url)
        self.clickable = {}
        if spec is None:
            return
        for href, _text in spec.links:
            escaped = href.replace("\\", "\\\\").replace('"', '\\"')
            self.clickable[f'a[href="{escaped}"]'] = href

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    # --- reading --------------------------------------------------------

    def evaluate(self, script: str, arg: Any = None) -> dict[str, Any]:
        self.evaluated.append((script, arg))
        spec = self._spec(self.url)
        if spec is None:
            raise RuntimeError(f"nothing rendered at {self.url}")
        return {
            "title": spec.title,
            "links": [{"href": href, "text": text} for href, text in spec.links],
            "forms": spec.forms,
            "elements": spec.elements,
        }

    # --- the sign-in path -----------------------------------------------

    def fill(self, selector: str, value: str, **_: Any) -> None:
        self.filled.append((selector, value))

    def press(self, selector: str, key: str, **_: Any) -> None:
        self.pressed.append((selector, key))


@dataclass
class _FakeResponse:
    url: str
    status: int

    @property
    def request(self) -> Any:
        return _FakeRequest()


class _FakeRequest:
    resource_type = "document"


__all__ = ["FakeLocator", "FakePage", "FakePageSpec", "button", "password_form"]
