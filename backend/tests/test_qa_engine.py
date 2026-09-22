"""Engine-level tests for the QA smoke suite.

These use a fake page object, so they are fast, deterministic, and do not
require Chromium. The real-browser path is covered separately in
``test_qa_api.py`` behind the ``playwright`` marker.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.engines.qa.models import (
    ConsoleError,
    NetworkFailure,
    RunStatus,
    TestResult,
    TestStatus,
    derive_run_status,
)
from app.engines.qa.smoke_suite import (
    SMOKE_SUITE,
    SmokeContext,
    check_application_reachability,
    check_dom_availability,
    check_page_title,
    collect_console_errors,
    collect_network_failures,
)


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class FakePage:
    """The slice of Playwright's Page that the smoke suite actually uses."""

    def __init__(
        self,
        *,
        status: int | None = 200,
        title: str = "Example App",
        html_length: int = 2048,
        element_count: int = 42,
        body_text: str = "hello",
        has_body: bool = True,
        final_url: str = "http://target.test/",
    ) -> None:
        self._status = status
        self._title = title
        self._html_length = html_length
        self._element_count = element_count
        self._body_text = body_text
        self._has_body = has_body
        self.url = final_url
        self.goto_calls: list[dict[str, Any]] = []

    def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None):
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        return None if self._status is None else FakeResponse(self._status)

    def title(self) -> str:
        return self._title

    def query_selector(self, selector: str):
        return object() if self._has_body else None

    def evaluate(self, script: str):
        if "outerHTML" in script:
            return self._html_length
        if "querySelectorAll" in script:
            return self._element_count
        raise AssertionError(f"unexpected evaluate: {script}")

    def inner_text(self, selector: str) -> str:
        return self._body_text


def make_context(page: FakePage, **kwargs: Any) -> SmokeContext:
    return SmokeContext(
        page=page,
        base_url=kwargs.pop("base_url", "http://target.test"),
        navigation_timeout_ms=kwargs.pop("navigation_timeout_ms", 15_000),
        **kwargs,
    )


# --- run status roll-up ------------------------------------------------


def _result(status: TestStatus) -> TestResult:
    return TestResult(name="x", status=status, duration_ms=1)


def test_all_passing_tests_make_a_passed_run() -> None:
    assert derive_run_status([_result(TestStatus.PASSED)] * 3) is RunStatus.PASSED


def test_one_failing_test_makes_a_failed_run() -> None:
    tests = [_result(TestStatus.PASSED), _result(TestStatus.FAILED)]
    assert derive_run_status(tests) is RunStatus.FAILED


def test_an_erroring_test_makes_an_error_run() -> None:
    tests = [_result(TestStatus.PASSED), _result(TestStatus.ERROR)]
    assert derive_run_status(tests) is RunStatus.ERROR


def test_a_real_failure_outranks_an_engine_error() -> None:
    """"The application is broken" is the more actionable headline."""
    tests = [_result(TestStatus.ERROR), _result(TestStatus.FAILED)]
    assert derive_run_status(tests) is RunStatus.FAILED


def test_empty_suite_is_not_reported_as_passing_by_accident() -> None:
    # No tests means nothing was proven, but the runner only reaches this
    # with a successful browser session, so passed is the honest answer.
    assert derive_run_status([]) is RunStatus.PASSED


# --- reachability ------------------------------------------------------


def test_reachability_navigates_to_the_target_base_url() -> None:
    page = FakePage()
    ctx = make_context(page, base_url="http://target.test:3000")

    details = check_application_reachability(ctx)

    assert page.goto_calls[0]["url"] == "http://target.test:3000"
    assert page.goto_calls[0]["timeout"] == 15_000
    assert details["http_status"] == 200
    assert details["requested_url"] == "http://target.test:3000"
    assert ctx.final_url == page.url


def test_reachability_fails_on_a_server_error_status() -> None:
    ctx = make_context(FakePage(status=500))
    with pytest.raises(AssertionError, match="HTTP 500"):
        check_application_reachability(ctx)


def test_reachability_fails_on_not_found() -> None:
    ctx = make_context(FakePage(status=404))
    with pytest.raises(AssertionError, match="HTTP 404"):
        check_application_reachability(ctx)


def test_reachability_tolerates_a_navigation_without_a_response() -> None:
    """Same-document navigation legitimately yields no response object."""
    details = check_application_reachability(make_context(FakePage(status=None)))
    assert details["http_status"] is None
    assert "note" in details


# --- page title --------------------------------------------------------


def test_title_check_records_the_actual_title() -> None:
    ctx = make_context(FakePage(title="Some Shop"))
    details = check_page_title(ctx)
    assert ctx.title == "Some Shop"
    assert details["title_length"] == len("Some Shop")


@pytest.mark.parametrize("title", ["", "   "])
def test_title_check_fails_when_the_title_is_blank(title: str) -> None:
    with pytest.raises(AssertionError, match="title"):
        check_page_title(make_context(FakePage(title=title)))


def test_title_check_does_not_assert_any_particular_text() -> None:
    """The suite must stay generic across targets."""
    for title in ("Mini E-Commerce", "Totally Different App", "x"):
        assert check_page_title(make_context(FakePage(title=title)))


# --- DOM ---------------------------------------------------------------


def test_dom_check_passes_on_a_normal_document() -> None:
    details = check_dom_availability(make_context(FakePage()))
    assert details["html_length"] == 2048
    assert details["element_count"] == 42
    assert details["body_text_length"] == len("hello")


def test_dom_check_fails_without_a_body() -> None:
    with pytest.raises(AssertionError, match="body"):
        check_dom_availability(make_context(FakePage(has_body=False)))


def test_dom_check_fails_on_empty_markup() -> None:
    with pytest.raises(AssertionError, match="empty"):
        check_dom_availability(make_context(FakePage(html_length=0)))


def test_dom_check_tolerates_an_empty_body_text() -> None:
    """A client-rendered app may still be painting at domcontentloaded."""
    details = check_dom_availability(make_context(FakePage(body_text="")))
    assert details["body_text_length"] == 0


# --- observation collectors -------------------------------------------


def test_console_collector_reports_what_the_listeners_gathered() -> None:
    ctx = make_context(
        FakePage(),
        console_errors=[
            ConsoleError(type="console_error", message="boom", location="a.js:1:1"),
            ConsoleError(type="page_error", message="kaboom"),
        ],
    )
    details = collect_console_errors(ctx)
    assert details["count"] == 2
    assert details["types"] == ["console_error", "page_error"]


def test_network_collector_reports_statuses() -> None:
    ctx = make_context(
        FakePage(),
        network_failures=[
            NetworkFailure(url="http://t/a", method="GET", status=500),
            NetworkFailure(url="http://t/b", method="GET", failure="ERR_ABORTED"),
        ],
    )
    details = collect_network_failures(ctx)
    assert details["count"] == 2
    assert details["statuses"] == [500]


def test_collectors_do_not_fail_the_run_when_problems_exist() -> None:
    """Observations are evidence for later phases, not smoke-test failures."""
    ctx = make_context(
        FakePage(),
        console_errors=[ConsoleError(type="console_error", message="x")] * 5,
        network_failures=[NetworkFailure(url="u", method="GET", status=500)] * 5,
    )
    assert collect_console_errors(ctx)["count"] == 5
    assert collect_network_failures(ctx)["count"] == 5


# --- suite shape -------------------------------------------------------


def test_suite_runs_reachability_first() -> None:
    """Every later check depends on the navigation it performs."""
    assert SMOKE_SUITE[0][0] == "Application Reachability"


def test_suite_covers_the_five_phase_two_checks() -> None:
    assert [name for name, _ in SMOKE_SUITE] == [
        "Application Reachability",
        "Page Title",
        "DOM Availability",
        "Console Error Collection",
        "Network Failure Collection",
    ]


def test_suite_contains_no_target_specific_logic() -> None:
    """Guard rail: the engine must not learn about one particular app."""
    from pathlib import Path

    import app.engines.qa.smoke_suite as suite_module

    source = Path(suite_module.__file__).read_text(encoding="utf-8").lower()
    for banned in ("mini e-commerce", "mini-ecommerce", "localhost:3000", "localhost:4000"):
        assert banned not in source, f"{banned!r} must not appear in the generic suite"
