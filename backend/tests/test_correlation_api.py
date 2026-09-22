"""Phase 6 API tests against the real MongoDB (focused implementation tests).

Assessments come from the real orchestrator with fake engines (as in the
Phase 4/5 API tests), so correlation always reads genuinely normalized
evidence. No test here needs an AI key; the one AI-supported case uses the
fake provider through the Phase 5 endpoint.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timezone
from typing import Any

import pytest

from app.engines.orchestrator.state_machine import utc_now
from tests.ai_fakes import FakeProvider
from tests.test_ai_analysis_api import (  # noqa: F401 - fixtures
    MISSING_ID,
    TECHNICAL_FIELDS,
    analyze,
    cleanup,
    db,
    run_assessment,
    use_provider,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def derived_cleanup(cleanup, settings) -> Iterator[dict[str, list[str]]]:
    try:
        yield cleanup
    finally:
        mongo, database = db(settings)
        with mongo:
            ids = cleanup["assessments"]
            if ids:
                database["issues"].delete_many({"assessment_id": {"$in": ids}})
                database["correlation_groups"].delete_many({"assessment_id": {"$in": ids}})


def correlate(client, assessment_id: str, **kwargs):
    return client.post(f"/assessments/{assessment_id}/correlation", **kwargs)


def snapshot(settings, assessment: dict[str, Any]) -> dict[str, Any]:
    """Raw collections exactly as stored."""
    from bson import ObjectId

    mongo, database = db(settings)
    with mongo:
        aid = assessment["id"]
        return {
            "evidence": list(database["evidence"].find({"assessment_id": aid}).sort("sequence", 1)),
            "ai": list(database["ai_analysis_logs"].find({"assessment_id": aid}).sort("_id", 1)),
            "qa": database["qa_runs"].find_one({"_id": ObjectId(assessment["qa_run_id"])}),
            "security": database["security_runs"].find_one(
                {"_id": ObjectId(assessment["security_run_id"])}
            ),
        }


# --- the operation --------------------------------------------------------------------


def test_correlation_creates_prioritized_issues_traceable_to_evidence(client, derived_cleanup) -> None:
    assessment = run_assessment(client, derived_cleanup)
    evidence = client.get(f"/assessments/{assessment['id']}/evidence").json()
    owned = {e["evidence_id"] for e in evidence}

    response = correlate(client, assessment["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    summary = body["correlation"]
    assert summary["status"] == "completed"
    assert summary["ai_analysis_id"] is None
    assert summary["evidence_excluded"] == {"passed": 1}
    assert summary["group_count"] == summary["issue_count"] == 3

    issues = body["issues"]
    assert [i["issue_id"] for i in issues] == ["ISSUE-001", "ISSUE-002", "ISSUE-003"]
    assert [i["priority"] for i in issues] == ["P2", "P2", "P3"]
    by_title = {i["title"]: i for i in issues}
    csp = by_title["CSP Header Not Set"]
    assert csp["tool_severity"] == "medium"
    assert csp["correlation_rule"] == "same_missing_header_and_origin"
    assert by_title["Page Title"]["type"] == "qa"
    assert by_title["Page Title"]["tool_severity"] is None
    for issue in issues:
        assert set(issue["evidence_ids"]) <= owned
        assert issue["priority_score"] == sum(f["points"] for f in issue["score_factors"])
        assert issue["priority_reasons"]

    after = client.get(f"/assessments/{assessment['id']}").json()
    assert after["status"] == "completed"
    assert after["correlation"]["status"] == "completed"
    for field in TECHNICAL_FIELDS:
        assert after[field] == assessment[field], field


def test_running_twice_is_idempotent(client, derived_cleanup, settings) -> None:
    assessment = run_assessment(client, derived_cleanup)
    first = correlate(client, assessment["id"]).json()["issues"]
    second = correlate(client, assessment["id"]).json()["issues"]

    def stable(issue):
        return {k: v for k, v in issue.items() if k != "updated_at"}

    assert [stable(i) for i in first] == [stable(i) for i in second]
    mongo, database = db(settings)
    with mongo:
        assert database["issues"].count_documents({"assessment_id": assessment["id"]}) == 3
        assert database["correlation_groups"].count_documents({"assessment_id": assessment["id"]}) == 3


def test_raw_collections_are_not_modified(client, derived_cleanup, settings, use_provider) -> None:
    use_provider(FakeProvider())
    assessment = run_assessment(client, derived_cleanup)
    assert analyze(client, assessment["id"]).status_code == 201
    before = snapshot(settings, assessment)
    assert correlate(client, assessment["id"]).status_code == 200
    assert snapshot(settings, assessment) == before


def test_completed_ai_analysis_is_linked_as_supporting_data(client, derived_cleanup, use_provider) -> None:
    use_provider(FakeProvider())
    assessment = run_assessment(client, derived_cleanup)
    analysis = analyze(client, assessment["id"]).json()

    body = correlate(client, assessment["id"]).json()
    assert body["correlation"]["ai_analysis_id"] == analysis["analysis_id"]
    page_title = next(i for i in body["issues"] if i["title"] == "Page Title")
    assert page_title["ai_finding_ids"] == ["AI-F-001"]
    assert page_title["confidence"] == "high"
    assert any(f["factor"] == "ai_support" and f["points"] == 8 for f in page_title["score_factors"])
    # AI supports the ranking; it never changes the tool severity.
    csp = next(i for i in body["issues"] if i["title"] == "CSP Header Not Set")
    assert csp["tool_severity"] == "medium"


# --- reads -------------------------------------------------------------------------------


def test_issue_and_group_reads(client, derived_cleanup) -> None:
    assessment = run_assessment(client, derived_cleanup)
    aid = assessment["id"]
    assert client.get(f"/assessments/{aid}/issues").json() == []
    correlate(client, aid)

    issues = client.get(f"/assessments/{aid}/issues").json()
    assert [i["issue_id"] for i in issues] == ["ISSUE-001", "ISSUE-002", "ISSUE-003"]
    assert len(client.get(f"/assessments/{aid}/issues", params={"type": "security"}).json()) == 2
    assert len(client.get(f"/assessments/{aid}/issues", params={"priority": "P3"}).json()) == 1
    assert client.get(f"/assessments/{aid}/issues", params={"priority": "P9"}).status_code == 422

    detail = client.get(f"/assessments/{aid}/issues/ISSUE-002")
    assert detail.status_code == 200
    assert detail.json()["evidence_refs"]
    assert client.get(f"/assessments/{aid}/issues/not-an-issue").status_code == 400
    assert client.get(f"/assessments/{aid}/issues/ISSUE-999").status_code == 404

    groups = client.get(f"/assessments/{aid}/correlation-groups").json()
    assert [g["correlation_group_id"] for g in groups] == ["CG-001", "CG-002", "CG-003"]
    assert all(g["correlation_reason"] and g["correlation_rule"] for g in groups)


# --- error contract ------------------------------------------------------------------------


def test_error_contract(client, derived_cleanup, settings) -> None:
    from bson import ObjectId

    assert correlate(client, "not-an-id").status_code == 400
    assert correlate(client, MISSING_ID).status_code == 404
    assert client.get(f"/assessments/{MISSING_ID}/issues").status_code == 404
    assert client.get("/assessments/bad/correlation-groups").status_code == 400

    assessment = run_assessment(client, derived_cleanup)
    aid = assessment["id"]
    assert correlate(client, aid, json={"target_id": "x"}).status_code == 422

    mongo, database = db(settings)
    with mongo:
        assessments = database["assessments"]
        assessments.update_one({"_id": ObjectId(aid)}, {"$set": {"status": "analyzing"}})
        try:
            assert correlate(client, aid).status_code == 409
        finally:
            assessments.update_one({"_id": ObjectId(aid)}, {"$set": {"status": "completed"}})

        # A run in progress blocks a second one...
        assessments.update_one(
            {"_id": ObjectId(aid)},
            {"$set": {"correlation": {"status": "running", "started_at": utc_now()}}},
        )
        assert correlate(client, aid).status_code == 409
        # ...until it is stale.
        stale = utc_now().replace(tzinfo=timezone.utc).timestamp() - settings.correlation_stale_seconds - 60
        from datetime import datetime

        assessments.update_one(
            {"_id": ObjectId(aid)},
            {"$set": {"correlation.started_at": datetime.fromtimestamp(stale, timezone.utc)}},
        )
        assert correlate(client, aid).status_code == 200
