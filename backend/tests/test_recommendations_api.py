"""Phase 8 API tests against the real MongoDB, with a clearly FAKE provider.

Assessments come from the real orchestrator with fake engines; the AI
analysis and the recommendations are answered by ``FakeProvider`` (never a
real model), always through the real AIAnalysisService.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from bson import ObjectId

from app.engines.ai.provider import AIProviderError, ProviderErrorCategory
from app.engines.orchestrator.state_machine import utc_now
from tests.ai_fakes import FakeProvider
from tests.recommendation_fakes import is_recommendation_prompt, recommendation_respond
from tests.test_ai_analysis_api import (  # noqa: F401 - fixtures
    MISSING_ID,
    TECHNICAL_FIELDS,
    analyze,
    cleanup,
    db,
    run_assessment,
    use_provider,
)
from tests.test_correlation_api import derived_cleanup  # noqa: F401 - fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def rec_cleanup(derived_cleanup, settings) -> Iterator[dict[str, list[str]]]:
    try:
        yield derived_cleanup
    finally:
        mongo, database = db(settings)
        with mongo:
            ids = derived_cleanup["assessments"]
            if ids:
                database["recommendations"].delete_many({"assessment_id": {"$in": ids}})


def correlate(client, aid: str):
    return client.post(f"/assessments/{aid}/correlation")


def generate(client, aid: str, **kwargs):
    return client.post(f"/assessments/{aid}/recommendations", **kwargs)


def ready(client, cleanup, use_provider, respond=None) -> dict[str, Any]:
    """Completed assessment + completed (fake) AI analysis + correlation."""
    use_provider(FakeProvider(respond=respond or recommendation_respond()))
    assessment = run_assessment(client, cleanup)
    assert analyze(client, assessment["id"]).status_code == 201
    assert correlate(client, assessment["id"]).status_code == 200
    return assessment


def snapshot(settings, assessment: dict[str, Any]) -> dict[str, Any]:
    mongo, database = db(settings)
    with mongo:
        aid = assessment["id"]
        by = {"assessment_id": aid}
        return {
            "evidence": list(database["evidence"].find(by).sort("sequence", 1)),
            "issues": list(database["issues"].find(by).sort("issue_number", 1)),
            "groups": list(database["correlation_groups"].find(by).sort("group_number", 1)),
            "ai": list(database["ai_analysis_logs"].find(by).sort("_id", 1)),
            "qa": database["qa_runs"].find_one({"_id": ObjectId(assessment["qa_run_id"])}),
            "security": database["security_runs"].find_one({"_id": ObjectId(assessment["security_run_id"])}),
        }


# --- generation ----------------------------------------------------------------------


def test_generation_is_grounded_advisory_and_ready_for_phase_9(client, rec_cleanup, use_provider) -> None:
    assessment = ready(client, rec_cleanup, use_provider)
    aid = assessment["id"]
    issues = {i["issue_id"]: i for i in client.get(f"/assessments/{aid}/issues").json()}
    evidence = {e["evidence_id"]: e for e in client.get(f"/assessments/{aid}/evidence").json()}

    response = generate(client, aid)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["status"] == "completed" and view["is_current"] is True
    assert view["generation"]["provider"] == "fake"  # a FAKE provider, never real-model verification
    assert view["ai_analysis_id"] == view["current_ai_analysis_id"]
    recs = view["recommendations"]
    assert [r["recommendation_id"] for r in recs] == [
        f"REC-{issues[i]['issue_number']:03d}" for i in sorted(issues)
    ]
    for r in recs:
        issue = issues[r["issue_id"]]
        assert r["advisory_status"] == "advisory"
        assert set(r["evidence_ids"]) <= set(issue["evidence_ids"])
        assert r["affected_components"] == issue["affected_components"]
        spec = r["retest"]
        assert spec["match_key"] == issue["group_key"] and spec["issue_id"] == issue["issue_id"]
        assert spec["target_id"] == assessment["target_id"]
        for check in spec["checks"]:
            assert evidence[check["evidence_id"]]["assessment_id"] == aid
            assert check["source"] == evidence[check["evidence_id"]]["source"]
        if issue["type"] == "security":
            assert (spec["retest_type"], spec["pass_condition"]) == ("security_rescan", "finding_absent")
        else:
            assert (spec["retest_type"], spec["pass_condition"]) == ("qa_recheck", "check_passes")

    detail = client.get(f"/assessments/{aid}/recommendations/{recs[0]['recommendation_id']}")
    assert detail.status_code == 200 and detail.json()["retest"] == recs[0]["retest"]
    text = json.dumps(view).lower()
    for word in ('"applied"', '"fixed"', '"remediated"', '"executed"', "raw_response"):
        assert word not in text


def test_generating_twice_from_the_same_analysis_is_idempotent(client, rec_cleanup, use_provider, settings) -> None:
    aid = ready(client, rec_cleanup, use_provider)["id"]
    first = generate(client, aid).json()["recommendations"]
    second = generate(client, aid).json()["recommendations"]
    assert [r["recommendation_id"] for r in first] == [r["recommendation_id"] for r in second]
    assert [r["created_at"] for r in first] == [r["created_at"] for r in second]
    mongo, database = db(settings)
    with mongo:
        assert database["recommendations"].count_documents({"assessment_id": aid}) == len(first)


def test_generation_changes_nothing_but_recommendations(client, rec_cleanup, use_provider, settings) -> None:
    assessment = ready(client, rec_cleanup, use_provider)
    aid = assessment["id"]
    before = snapshot(settings, assessment)
    assessment_before = client.get(f"/assessments/{aid}").json()
    assert generate(client, aid).status_code == 200
    assert snapshot(settings, assessment) == before
    after = client.get(f"/assessments/{aid}").json()
    for field in (*TECHNICAL_FIELDS, "status", "correlation", "ai_analysis_id", "ai_analysis_status"):
        assert after[field] == assessment_before[field], field
    assert after["recommendation"]["status"] == "completed"


def test_newer_ai_analysis_is_explicit_and_sets_are_never_mixed(client, rec_cleanup, use_provider) -> None:
    aid = ready(client, rec_cleanup, use_provider)["id"]
    old = generate(client, aid).json()
    assert analyze(client, aid).status_code == 201  # a newer completed analysis

    stale = client.get(f"/assessments/{aid}/recommendations").json()
    assert stale["is_current"] is False and stale["ai_analysis_id"] == old["ai_analysis_id"]
    blocked = generate(client, aid)
    assert blocked.status_code == 409 and "Correlate" in blocked.json()["detail"]

    assert correlate(client, aid).status_code == 200
    new = generate(client, aid).json()
    assert new["ai_analysis_id"] != old["ai_analysis_id"] and new["is_current"] is True
    assert {s["ai_analysis_id"] for s in new["sets"]} == {old["ai_analysis_id"], new["ai_analysis_id"]}
    older = client.get(f"/assessments/{aid}/recommendations", params={"ai_analysis_id": old["ai_analysis_id"]}).json()
    assert [r["ai_analysis_id"] for r in older["recommendations"]] == [old["ai_analysis_id"]] * len(old["recommendations"])


# --- failures are recorded, nothing is repaired -------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "category"),
    [
        (lambda a, p: "not json", "invalid_json"),
        (lambda a, p: a["recommendations"][0].update(applied=True), "schema_violation"),
        (lambda a, p: a["recommendations"][0].update(issue_id="ISSUE-999"), "unknown_issue_reference"),
        (lambda a, p: a["recommendations"][0].update(evidence_ids=["EV-999"]), "unknown_evidence_reference"),
        (lambda a, p: a["recommendations"][0]["retest"].update(target_component="http://elsewhere.invalid"),
         "invalid_retest_specification"),
    ],
    ids=["invalid_json", "schema", "unknown_issue", "unknown_evidence", "invalid_retest"],
)
def test_rejected_answers_fail_the_generation(client, rec_cleanup, use_provider, mutate, category) -> None:
    aid = ready(client, rec_cleanup, use_provider, recommendation_respond(mutate))["id"]
    response = generate(client, aid)
    assert response.status_code == 502 and category in response.json()["detail"]
    view = client.get(f"/assessments/{aid}/recommendations").json()
    assert view["status"] == "failed" and view["generation"]["error"]["category"] == category
    assert view["recommendations"] == []


def test_provider_failure_keeps_existing_recommendations(client, rec_cleanup, use_provider) -> None:
    aid = ready(client, rec_cleanup, use_provider)["id"]
    existing = generate(client, aid).json()["recommendations"]

    def failing(prompt: str) -> str:
        if is_recommendation_prompt(prompt):
            raise AIProviderError(ProviderErrorCategory.AUTHENTICATION, "The provider rejected the key.")
        return recommendation_respond()(prompt)

    use_provider(FakeProvider(respond=failing))
    response = generate(client, aid)
    assert response.status_code == 502 and "authentication" in response.json()["detail"]
    view = client.get(f"/assessments/{aid}/recommendations").json()
    assert view["status"] == "failed"
    assert [r["updated_at"] for r in view["recommendations"]] == [r["updated_at"] for r in existing]


# --- preconditions and error contract ---------------------------------------------------------


def test_preconditions_are_explicit_409s(client, rec_cleanup, use_provider, settings) -> None:
    use_provider(FakeProvider(respond=recommendation_respond()))
    aid = run_assessment(client, rec_cleanup)["id"]
    no_analysis = generate(client, aid)
    assert no_analysis.status_code == 409 and "AI analysis" in no_analysis.json()["detail"]

    assert correlate(client, aid).status_code == 200  # correlated before any analysis
    assert analyze(client, aid).status_code == 201
    assert generate(client, aid).status_code == 409  # issues built without this analysis

    mongo, database = db(settings)
    with mongo:
        assessments = database["assessments"]
        assessments.update_one({"_id": ObjectId(aid)}, {"$unset": {"correlation": ""}})
        assert "Correlate" in generate(client, aid).json()["detail"]
        assert correlate(client, aid).status_code == 200

        assessments.update_one({"_id": ObjectId(aid)}, {"$set": {"status": "analyzing"}})
        try:
            assert generate(client, aid).status_code == 409
        finally:
            assessments.update_one({"_id": ObjectId(aid)}, {"$set": {"status": "completed"}})

        assessments.update_one(
            {"_id": ObjectId(aid)},
            {"$set": {"recommendation": {"status": "running", "started_at": utc_now(), "generation_id": "x"}}},
        )
        assert generate(client, aid).status_code == 409
        assessments.update_one({"_id": ObjectId(aid)}, {"$unset": {"recommendation": ""}})
    assert generate(client, aid).status_code == 200


def test_error_contract(client, rec_cleanup, use_provider) -> None:
    assert generate(client, "not-an-id").status_code == 400
    assert generate(client, MISSING_ID).status_code == 404
    assert client.get(f"/assessments/{MISSING_ID}/recommendations").status_code == 404

    aid = ready(client, rec_cleanup, use_provider)["id"]
    assert generate(client, aid, json={"issue_ids": ["ISSUE-001"]}).status_code == 422
    empty = client.get(f"/assessments/{aid}/recommendations").json()
    assert empty["status"] == "not_generated" and empty["recommendations"] == []
    assert generate(client, aid, json={}).status_code == 200
    assert client.get(f"/assessments/{aid}/recommendations/REC-1").status_code == 400
    assert client.get(f"/assessments/{aid}/recommendations/REC-999").status_code == 404
    assert client.get(f"/assessments/{aid}/recommendations", params={"ai_analysis_id": "zz"}).status_code == 422
