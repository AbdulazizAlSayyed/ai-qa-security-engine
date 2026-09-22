"""Phase 10 API tests against the real MongoDB.

FAKE engines and a FAKE AI provider (labelled) produce the source data, as
in the Phase 8/9 tests. Report generation itself is exercised for real:
real service, real audit, real HTML / PDF rendering, real `reports`
documents. Rendered files go to a pytest temp folder, never to REPORTS_ROOT.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from bson import ObjectId
from pymongo.errors import PyMongoError

from tests.test_ai_analysis_api import MISSING_ID, cleanup, db, run_assessment, use_provider  # noqa: F401 - fixtures
from tests.test_assessments_api import FakeQaEngine
from tests.test_correlation_api import derived_cleanup  # noqa: F401 - fixture
from tests.test_recommendations_api import rec_cleanup  # noqa: F401 - fixture
from tests.test_retests_api import (  # noqa: F401 - fixtures
    CSP,
    PAGE_TITLE,
    FakeRetestEngines,
    prepared,
    qa_engine_error,
    retest,
    retest_cleanup,
    security_with,
    use_engines,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def report_cleanup(retest_cleanup, settings) -> Iterator[dict[str, list[str]]]:
    try:
        yield retest_cleanup
    finally:
        mongo, database = db(settings)
        with mongo:
            if retest_cleanup["assessments"]:
                database["reports"].delete_many({"assessment_id": {"$in": retest_cleanup["assessments"]}})


@pytest.fixture
def use_reports(client, settings, tmp_path) -> Iterator:
    """Real ReportService with REPORTS_ROOT pointed at a temp folder."""
    from app.api.dependencies import get_report_service
    from app.core.database import get_database
    from app.services.report_service import ReportService

    state: dict[str, Any] = {"settings": settings.model_copy(update={"reports_root": tmp_path}), "wrap": None}

    def install(**updates) -> dict[str, Any]:
        state["settings"] = state["settings"].model_copy(update=updates)
        return state

    def override() -> ReportService:
        service = ReportService(db=get_database(), settings=state["settings"])
        if state["wrap"]:
            state["wrap"](service)
        return service

    client.app.dependency_overrides[get_report_service] = override
    state["install"] = install
    state["root"] = tmp_path
    try:
        yield state
    finally:
        client.app.dependency_overrides.pop(get_report_service, None)


def report(client, aid: str, **kwargs):
    return client.post(f"/assessments/{aid}/reports", **kwargs)


def full_chain(client, cleanup, use_provider, use_engines) -> tuple[str, dict[str, str], FakeRetestEngines]:
    """Assessment -> fake AI -> correlation -> recommendations -> FAIL, PASS and execution-failed retests."""
    engines = use_engines(FakeRetestEngines())
    assessment, recs = prepared(client, cleanup, use_provider)
    aid = assessment["id"]
    assert retest(client, aid, recs[CSP]).json()["verdict"] == "FAIL"
    engines.security_outcome = security_with()
    assert retest(client, aid, recs[CSP]).json()["verdict"] == "PASS"
    engines.qa_outcome = qa_engine_error()
    assert retest(client, aid, recs[PAGE_TITLE]).status_code == 502
    return aid, recs, engines


# --- success, content, files ---------------------------------------------------------------


def test_full_chain_report(client, report_cleanup, use_provider, use_engines, use_reports, settings) -> None:
    aid, recs, _ = full_chain(client, report_cleanup, use_provider, use_engines)
    response = report(client, aid, json={})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["report_id"], body["status"], body["reused"], body["report_version"]) == ("REPORT-001", "completed", False, "1.0")
    assert body["traceability"]["status"] == "passed" and body["traceability"]["errors"] == []
    assert body["traceability"]["links_checked"] > 20
    assert body["summary"]["retests"] == {"total": 3, "passed": 1, "failed": 1, "execution_failed": 1, "running": 0}
    snap = body["source_snapshot"]
    assert snap["recommendation_count"] == len(recs) and snap["retest_count"] == 3 and snap["issue_count"] >= 2
    assert set(body["artifacts"]) == {"html", "pdf"} and body["formats"] == ["html", "pdf"]
    assert all("path" not in a and len(a["sha256"]) == 64 and a["size_bytes"] > 0 for a in body["artifacts"].values())

    html = client.get(f"/assessments/{aid}/reports/REPORT-001/html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in html.headers["content-security-policy"]
    text = html.text
    for needle in ("Executive summary", "Traceability audit", "ADVISORY ONLY", "EV-001", "ISSUE-001", "REC-001",
                   "RETEST-001", "RETEST-003", "Execution failed", "fake-model"):
        assert needle in text, needle
    pdf = client.get(f"/assessments/{aid}/reports/REPORT-001/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-") and b"Traceability audit" in pdf.content
    assert "attachment" in pdf.headers["content-disposition"]
    assert (use_reports["root"] / "assessments" / aid / "REPORT-001.pdf").stat().st_size == len(pdf.content)

    mongo, database = db(settings)
    with mongo:
        stored = database["reports"].find_one({"assessment_id": aid})
    # References and small snapshots only - never copied source collections or raw payloads.
    assert not {"evidence", "issues", "recommendations", "retests", "qa_run", "security_run", "html", "pdf"} & set(stored)
    assert len(str(stored)) < 20_000 and "evidence_payload" not in str(stored)


def test_regeneration_is_idempotent_until_the_data_changes(client, report_cleanup, use_provider, use_engines, use_reports, settings) -> None:
    aid, recs, engines = full_chain(client, report_cleanup, use_provider, use_engines)
    first = report(client, aid).json()
    again = report(client, aid)
    assert again.status_code == 200 and again.json()["reused"] is True and again.json()["report_id"] == first["report_id"]
    engines.security_outcome = None  # a new retest changes the source data
    assert retest(client, aid, recs[CSP]).status_code == 201
    newer = report(client, aid)
    assert newer.status_code == 201 and newer.json()["report_id"] == "REPORT-002"
    assert [r["report_id"] for r in client.get(f"/assessments/{aid}/reports").json()] == ["REPORT-002", "REPORT-001"]
    assert client.get(f"/assessments/{aid}/reports/REPORT-001").json()["source_fingerprint"] == first["source_fingerprint"]


def test_minimal_and_partial_assessments(client, report_cleanup, use_reports) -> None:
    plain = run_assessment(client, report_cleanup)
    body = report(client, plain["id"]).json()
    assert body["status"] == "completed" and body["summary"]["ai_analysis_status"] == "not_analyzed"
    assert body["summary"]["recommendation_status"] == "not_generated" and body["summary"]["retests"]["total"] == 0
    html = client.get(f"/assessments/{plain['id']}/reports/{body['report_id']}/html").text
    assert "No completed AI analysis exists" in html and "No recommendations have been generated." in html

    partial = run_assessment(client, report_cleanup, qa=FakeQaEngine(exc=RuntimeError("no browser")))
    assert partial["partial"] is True and partial["status"] == "completed"
    body = report(client, partial["id"]).json()
    assert body["status"] == "completed" and body["summary"]["partial"] is True
    assert "PARTIAL ASSESSMENT" in client.get(f"/assessments/{partial['id']}/reports/{body['report_id']}/html").text


# --- error contract ------------------------------------------------------------------------------


def test_error_contract(client, report_cleanup, use_reports, settings) -> None:
    assert report(client, "not-an-id").status_code == 400
    assert report(client, MISSING_ID).status_code == 404
    assert client.get(f"/assessments/{MISSING_ID}/reports").status_code == 404
    aid = run_assessment(client, report_cleanup)["id"]
    assert report(client, aid, json={"evidence": []}).status_code == 422
    assert client.get(f"/assessments/{aid}/reports/REPORT-1").status_code == 400
    assert client.get(f"/assessments/{aid}/reports/REPORT-999").status_code == 404
    assert client.get(f"/assessments/{aid}/reports/REPORT-999/pdf").status_code == 404
    assert client.get(f"/assessments/{aid}/reports", params={"limit": 0}).status_code == 422
    mongo, database = db(settings)
    with mongo:
        for state in ("analyzing", "running", "failed"):
            database["assessments"].update_one({"_id": ObjectId(aid)}, {"$set": {"status": state}})
            response = report(client, aid)
            assert response.status_code == 409 and state in response.json()["detail"]
        database["assessments"].update_one({"_id": ObjectId(aid)}, {"$set": {"status": "completed", "correlation": {"status": "running"}}})
        assert report(client, aid).status_code == 409
        database["assessments"].update_one({"_id": ObjectId(aid)}, {"$set": {"correlation": None}})
        assert database["reports"].count_documents({"assessment_id": aid}) == 0
    assert report(client, aid).status_code == 201


def test_broken_traceability_is_refused_and_recorded_once(client, report_cleanup, use_provider, use_engines, use_reports, settings) -> None:
    use_engines(FakeRetestEngines())
    assessment, _ = prepared(client, report_cleanup, use_provider)
    aid = assessment["id"]
    other = run_assessment(client, report_cleanup)
    mongo, database = db(settings)
    with mongo:
        foreign = database["evidence"].find_one({"assessment_id": other["id"]})["evidence_id"]
        issue = database["issues"].find_one({"assessment_id": aid, "issue_id": "ISSUE-001"})
        database["issues"].update_one({"_id": issue["_id"]}, {"$push": {"evidence_ids": foreign}})
        try:
            first = report(client, aid)
            assert first.status_code == 409
            detail = first.json()["detail"]
            assert "REPORT-001" in detail and "issue->evidence" in detail and "different assessment" in detail
            assert report(client, aid).status_code == 409  # same broken data: no second record
            stored = list(database["reports"].find({"assessment_id": aid}))
            assert len(stored) == 1 and stored[0]["status"] == "failed" and "dedupe_key" not in stored[0]
            assert stored[0]["traceability"]["status"] == "failed" and stored[0]["artifacts"] == {}
            assert not (use_reports["root"] / "assessments" / aid).exists()  # nothing rendered
        finally:
            database["issues"].update_one({"_id": issue["_id"]}, {"$pull": {"evidence_ids": foreign}})
    ok = report(client, aid)
    assert ok.status_code == 201 and ok.json()["report_id"] == "REPORT-002"


def test_secrets_are_redacted_and_a_configured_secret_blocks_the_report(client, report_cleanup, use_reports, settings) -> None:
    aid = run_assessment(client, report_cleanup)["id"]
    mongo, database = db(settings)
    with mongo:
        database["evidence"].update_one(
            {"assessment_id": aid, "sequence": 0},
            {"$set": {"actual": "Authorization: Bearer abcdefghijklmnop123 password=Sup3rS3cret! sk-proj-" + "B" * 40}},
        )
        body = report(client, aid).json()
        html = client.get(f"/assessments/{aid}/reports/{body['report_id']}/html").text
        pdf = client.get(f"/assessments/{aid}/reports/{body['report_id']}/pdf").content
        for needle in ("abcdefghijklmnop123", "Sup3rS3cret", "B" * 40):
            assert needle not in html and needle.encode() not in pdf
        assert "[REDACTED]" in html

        use_reports["install"](zap_api_key="zap-configured-key-42")
        database["evidence"].update_one({"assessment_id": aid, "sequence": 0}, {"$set": {"title": "leaked zap-configured-key-42"}})
        failed = report(client, aid)
        assert failed.status_code == 500 and "secret_leak" in failed.json()["detail"]
        assert "zap-configured-key-42" not in failed.json()["detail"]
        record = database["reports"].find_one({"assessment_id": aid, "status": "failed"})
    assert record["error"]["category"] == "secret_leak" and record["artifacts"] == {}
    assert not (use_reports["root"] / "assessments" / aid / f"{record['report_id']}.html").exists()


def test_persistence_error_and_tampered_file(client, report_cleanup, use_reports, settings) -> None:
    aid = run_assessment(client, report_cleanup)["id"]
    body = report(client, aid).json()
    path = use_reports["root"] / "assessments" / aid / f"{body['report_id']}.html"
    path.write_text(path.read_text(encoding="utf-8") + "<!-- edited -->", encoding="utf-8")
    tampered = client.get(f"/assessments/{aid}/reports/{body['report_id']}/html")
    assert tampered.status_code == 500 and "SHA-256" in tampered.json()["detail"]

    class Failing:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def insert_one(self, *args, **kwargs):
            raise PyMongoError("simulated outage")

    def wrap(service) -> None:
        service._reports = Failing(service._reports)

    mongo, database = db(settings)
    with mongo:
        database["reports"].delete_many({"assessment_id": aid})  # so the next POST must insert
    use_reports["wrap"] = wrap
    response = client.post(f"/assessments/{aid}/reports")
    assert response.status_code == 500 and "PyMongoError" in response.json()["detail"]
    assert "simulated outage" not in response.json()["detail"]


def test_report_indexes(client, settings) -> None:
    mongo, database = db(settings)
    with mongo:
        indexes = database["reports"].index_information()
    assert indexes["reports_by_number"]["unique"] is True
    assert indexes["reports_dedupe"]["unique"] is True
    assert indexes["reports_dedupe"]["partialFilterExpression"] == {"dedupe_key": {"$exists": True}}
