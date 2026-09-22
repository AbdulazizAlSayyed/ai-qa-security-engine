"""Phase 9 API tests against the real MongoDB.

FAKE engines and a FAKE AI provider throughout: the original assessment and
every retest run through the real services (QaService / SecurityService,
normalizer, RetestService), but the QA and security *engines* are the
test-suite fakes, so no browser, scanner or target is touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from bson import ObjectId

from app.engines.qa.models import QaRunOutcome
from app.engines.qa.models import RunStatus as QaRunStatus
from app.engines.qa.models import TestResult, TestStatus
from app.engines.security.models import ComponentResult, ComponentStatus, SecurityRunOutcome
from app.engines.security.models import RunStatus as SecurityRunStatus
from tests.ai_fakes import FakeProvider
from tests.recommendation_fakes import recommendation_respond
from tests.test_ai_analysis_api import (  # noqa: F401 - fixtures
    MISSING_ID,
    TECHNICAL_FIELDS,
    analyze,
    cleanup,
    db,
    run_assessment,
    use_provider,
)
from tests.test_assessments_api import qa_outcome, security_outcome
from tests.test_correlation_api import derived_cleanup  # noqa: F401 - fixture
from tests.test_recommendations_api import rec_cleanup  # noqa: F401 - fixture

pytestmark = pytest.mark.integration

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def retest_cleanup(rec_cleanup, settings) -> Iterator[dict[str, list[str]]]:
    try:
        yield rec_cleanup
    finally:
        mongo, database = db(settings)
        with mongo:
            if rec_cleanup["assessments"]:
                database["retests"].delete_many({"assessment_id": {"$in": rec_cleanup["assessments"]}})
            if rec_cleanup["targets"]:
                for name in ("qa_runs", "security_runs"):
                    database[name].delete_many({"target_id": {"$in": rec_cleanup["targets"]}, "scope.purpose": "retest"})


# --- fake engines (labelled) -------------------------------------------------------------


class FakeRetestEngines:
    """Records the configuration each engine was given, returns a chosen outcome."""

    def __init__(self, qa: QaRunOutcome | None = None, security: SecurityRunOutcome | None = None):
        self.qa_outcome, self.security_outcome = qa, security
        self.qa_configs: list[Any] = []
        self.security_configs: list[Any] = []

    def qa(self, base_url, config) -> QaRunOutcome:
        self.qa_configs.append(config)
        return self.qa_outcome or qa_outcome()

    def security(
        self, *, base_url, api_url, source_path, config, authorization_readiness=None
    ) -> SecurityRunOutcome:
        self.security_configs.append(config)
        return self.security_outcome or security_outcome()


def qa_passing() -> QaRunOutcome:
    return QaRunOutcome(
        status=QaRunStatus.PASSED, started_at=NOW, finished_at=NOW, duration_ms=10,
        tests=[
            TestResult(name="Application Reachability", status=TestStatus.PASSED, duration_ms=1,
                       url="http://target.invalid/", details={"http_status": 200}),
            TestResult(name="Page Title", status=TestStatus.PASSED, duration_ms=1,
                       url="http://target.invalid/", title="Now titled", details={"title_length": 11}),
        ],
        metadata={"browser": "fake"},
    )


def qa_engine_error() -> QaRunOutcome:
    return QaRunOutcome(status=QaRunStatus.ERROR, started_at=NOW, finished_at=NOW, duration_ms=1,
                        tests=[], metadata={"browser": "fake"}, error="Browser could not launch")


def security_with(zap_status: ComponentStatus = ComponentStatus.COMPLETED, findings=None) -> SecurityRunOutcome:
    return SecurityRunOutcome(
        status=SecurityRunStatus.COMPLETED, started_at=NOW, finished_at=NOW, duration_ms=5,
        components=[
            ComponentResult(name="zap", status=zap_status, findings=findings or []),
            ComponentResult(name="api_probes", status=ComponentStatus.SKIPPED, detail="scoped out"),
        ],
        engine_metadata={"engine_version": "fake"},
    )


@pytest.fixture
def use_engines(client) -> Iterator:
    from app.api.dependencies import get_retest_service
    from app.core.config import get_settings
    from app.core.database import get_database
    from app.services.qa_service import QaService
    from app.services.retest_service import RetestService
    from app.services.security_service import SecurityService
    from app.services.target_service import TargetService

    def install(engines: FakeRetestEngines) -> FakeRetestEngines:
        def override() -> RetestService:
            database, settings = get_database(), get_settings()
            targets = TargetService(database)
            return RetestService(
                db=database,
                qa=QaService(db=database, targets=targets, settings=settings, engine=engines.qa),
                security=SecurityService(db=database, targets=targets, settings=settings, engine=engines.security),
                settings=settings,
            )

        client.app.dependency_overrides[get_retest_service] = override
        return engines

    try:
        yield install
    finally:
        client.app.dependency_overrides.pop(get_retest_service, None)


def prepared(client, cleanup, use_provider) -> tuple[dict[str, Any], dict[str, str]]:
    """Assessment -> fake AI analysis -> correlation -> recommendations. Returns REC by issue title."""
    use_provider(FakeProvider(respond=recommendation_respond()))
    assessment = run_assessment(client, cleanup)
    aid = assessment["id"]
    assert analyze(client, aid).status_code == 201
    assert client.post(f"/assessments/{aid}/correlation").status_code == 200
    view = client.post(f"/assessments/{aid}/recommendations").json()
    issues = {i["issue_id"]: i["title"] for i in client.get(f"/assessments/{aid}/issues").json()}
    return assessment, {issues[r["issue_id"]]: r["recommendation_id"] for r in view["recommendations"]}


def retest(client, aid: str, rec: str, **kwargs):
    return client.post(f"/assessments/{aid}/recommendations/{rec}/retest", **kwargs)


CSP = "CSP Header Not Set"
PAGE_TITLE = "Page Title"


# --- verdicts --------------------------------------------------------------------------------


def test_security_finding_still_present_is_fail(client, retest_cleanup, use_provider, use_engines, settings) -> None:
    engines = use_engines(FakeRetestEngines())
    assessment, recs = prepared(client, retest_cleanup, use_provider)
    response = retest(client, assessment["id"], recs[CSP])
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["retest_id"], body["status"], body["verdict"]) == ("RETEST-001", "completed", "FAIL")
    assert body["type"] == "security_rescan" and body["plan"]["components"] == ["zap"]
    assert all(o["correlation_key"] == body["match_key"] for o in body["observations"])
    assert body["matched_evidence_ids"] == [c["evidence_id"] for c in body["checks"]]
    # Scoped: only ZAP was switched on for the engine.
    config = engines.security_configs[-1]
    assert config.zap.enabled is True or settings.zap_enabled is False
    assert config.api_probes_enabled is False and config.semgrep.enabled is False
    mongo, database = db(settings)
    with mongo:
        raw = database["security_runs"].find_one({"_id": ObjectId(body["source_run_ids"][0])})
    assert raw["scope"] == {"purpose": "retest", "components": ["zap"]}


def test_security_finding_gone_is_pass(client, retest_cleanup, use_provider, use_engines) -> None:
    use_engines(FakeRetestEngines(security=security_with()))
    assessment, recs = prepared(client, retest_cleanup, use_provider)
    body = retest(client, assessment["id"], recs[CSP]).json()
    assert (body["status"], body["verdict"]) == ("completed", "PASS")
    assert body["matched_evidence_ids"] == [] and body["observations"] == []


def test_qa_check_passes_is_pass_and_failing_is_fail(client, retest_cleanup, use_provider, use_engines) -> None:
    engines = use_engines(FakeRetestEngines(qa=qa_passing()))
    assessment, recs = prepared(client, retest_cleanup, use_provider)
    passed = retest(client, assessment["id"], recs[PAGE_TITLE]).json()
    assert (passed["type"], passed["verdict"]) == ("qa_recheck", "PASS")
    assert engines.qa_configs[-1].checks == ("Page Title",)  # only the specified check

    engines.qa_outcome = qa_outcome()  # the title is still missing
    failed = retest(client, assessment["id"], recs[PAGE_TITLE]).json()
    assert (failed["retest_id"], failed["verdict"]) == ("RETEST-002", "FAIL")


@pytest.mark.parametrize(
    "engines",
    [
        lambda: FakeRetestEngines(security=security_with(ComponentStatus.FAILED)),
        lambda: FakeRetestEngines(qa=qa_engine_error()),
    ],
    ids=["scanner-failed", "qa-engine-error"],
)
def test_engine_failure_is_a_failed_execution_not_a_fail_verdict(client, retest_cleanup, use_provider, use_engines, engines) -> None:
    use_engines(engines())
    assessment, recs = prepared(client, retest_cleanup, use_provider)
    rec = recs[CSP] if engines().security_outcome else recs[PAGE_TITLE]
    response = retest(client, assessment["id"], rec)
    assert response.status_code == 502 and "RETEST-001" in response.json()["detail"]
    stored = client.get(f"/assessments/{assessment['id']}/retests/RETEST-001").json()
    assert (stored["status"], stored["verdict"]) == ("failed", None)
    assert stored["error"]["category"] == "execution_failed" and stored["source_run_ids"]


# --- history, immutability, lock ------------------------------------------------------------------


def test_every_execution_is_kept_and_numbers_are_never_reused(client, retest_cleanup, use_provider, use_engines, settings) -> None:
    use_engines(FakeRetestEngines())
    assessment, recs = prepared(client, retest_cleanup, use_provider)
    aid = assessment["id"]
    first = retest(client, aid, recs[CSP]).json()
    second = retest(client, aid, recs[CSP]).json()
    third = retest(client, aid, recs[PAGE_TITLE]).json()
    assert [first["retest_id"], second["retest_id"], third["retest_id"]] == ["RETEST-001", "RETEST-002", "RETEST-003"]
    assert client.get(f"/assessments/{aid}/retests/RETEST-001").json() == first
    history = client.get(f"/assessments/{aid}/retests", params={"recommendation_id": recs[CSP]}).json()
    assert [r["retest_id"] for r in history] == ["RETEST-002", "RETEST-001"]
    assert [r["retest_id"] for r in client.get(f"/assessments/{aid}/retests").json()] == ["RETEST-003", "RETEST-002", "RETEST-001"]


def test_retests_change_nothing_they_read(client, retest_cleanup, use_provider, use_engines, settings) -> None:
    use_engines(FakeRetestEngines())
    assessment, recs = prepared(client, retest_cleanup, use_provider)
    aid = assessment["id"]

    def snapshot() -> dict[str, Any]:
        mongo, database = db(settings)
        with mongo:
            by = {"assessment_id": aid}
            data = {name: list(database[name].find(by).sort("_id", 1)) for name in
                    ("evidence", "issues", "correlation_groups", "recommendations", "ai_analysis_logs")}
            data["assessment"] = database["assessments"].find_one({"_id": ObjectId(aid)})
            return data

    before = snapshot()
    retest(client, aid, recs[CSP])
    retest(client, aid, recs[PAGE_TITLE])
    assert snapshot() == before
    assert client.get(f"/assessments/{aid}").json()["status"] == "completed"


def test_concurrent_retest_is_refused_and_a_stale_lock_recovers(client, retest_cleanup, use_provider, use_engines, settings) -> None:
    use_engines(FakeRetestEngines())
    assessment, recs = prepared(client, retest_cleanup, use_provider)
    aid = assessment["id"]
    first = retest(client, aid, recs[CSP]).json()

    mongo, database = db(settings)
    with mongo:
        running = {**{k: v for k, v in database["retests"].find_one({"retest_id": "RETEST-001", "assessment_id": aid}).items() if k != "_id"},
                   "retest_id": "RETEST-002", "retest_number": 2, "status": "running", "verdict": None,
                   "started_at": datetime.now(timezone.utc)}
        database["retests"].insert_one(running)
        blocked = retest(client, aid, recs[CSP])
        assert blocked.status_code == 409 and "already running" in blocked.json()["detail"]
        # Other recommendations are not blocked.
        assert retest(client, aid, recs[PAGE_TITLE]).status_code == 201  # RETEST-003

        database["retests"].update_one(
            {"assessment_id": aid, "retest_number": 2},
            {"$set": {"started_at": datetime.now(timezone.utc) - timedelta(seconds=settings.retest_stale_seconds + 60)}},
        )
        recovered = retest(client, aid, recs[CSP])
        assert recovered.status_code == 201 and recovered.json()["retest_id"] == "RETEST-004"
        abandoned = database["retests"].find_one({"assessment_id": aid, "retest_number": 2})
    assert (abandoned["status"], abandoned["verdict"], abandoned["error"]["category"]) == ("failed", None, "abandoned")
    assert first["retest_id"] == "RETEST-001"


# --- error contract ----------------------------------------------------------------------------------


def test_error_contract(client, retest_cleanup, use_provider, use_engines, settings) -> None:
    use_engines(FakeRetestEngines())
    assert retest(client, "not-an-id", "REC-001").status_code == 400
    assert retest(client, MISSING_ID, "REC-001").status_code == 404
    assert client.get(f"/assessments/{MISSING_ID}/retests").status_code == 404

    assessment, recs = prepared(client, retest_cleanup, use_provider)
    aid, rec = assessment["id"], recs[CSP]
    assert retest(client, aid, "REC-1").status_code == 400
    assert retest(client, aid, "REC-999").status_code == 404
    assert retest(client, aid, rec, params={"ai_analysis_id": "nope"}).status_code == 400
    assert retest(client, aid, rec, json={"retest_type": "security_rescan"}).status_code == 422
    assert client.get(f"/assessments/{aid}/retests/RETEST-1").status_code == 400
    assert client.get(f"/assessments/{aid}/retests/RETEST-999").status_code == 404
    assert client.get(f"/assessments/{aid}/retests", params={"limit": 0}).status_code == 422

    mongo, database = db(settings)
    with mongo:
        assessments, recommendations = database["assessments"], database["recommendations"]
        assessments.update_one({"_id": ObjectId(aid)}, {"$set": {"status": "analyzing"}})
        try:
            assert retest(client, aid, rec).status_code == 409
        finally:
            assessments.update_one({"_id": ObjectId(aid)}, {"$set": {"status": "completed"}})

        query = {"assessment_id": aid, "recommendation_id": rec}
        original = recommendations.find_one(query)["retest"]
        try:
            recommendations.update_one(query, {"$set": {"retest.retest_type": "full_scan"}})
            assert retest(client, aid, rec).status_code == 409  # unsupported type
            recommendations.update_one(query, {"$set": {"retest": {**original, "match_key": "forged"}}})
            assert retest(client, aid, rec).status_code == 500  # spec no longer matches its issue

            other = run_assessment(client, retest_cleanup)
            foreign = database["evidence"].find_one({"assessment_id": other["id"], "source": "zap"})
            forged = {**original, "checks": [{**original["checks"][0], "evidence_id": foreign["evidence_id"]}]}
            recommendations.update_one(query, {"$set": {"retest": forged}})
            response = retest(client, aid, rec)
            assert response.status_code == 500 and "this assessment" in response.json()["detail"]
        finally:
            recommendations.update_one(query, {"$set": {"retest": original}})
        assert database["retests"].count_documents({"assessment_id": aid}) == 0  # nothing ran
    assert retest(client, aid, rec).status_code == 201
