"""AI analysis API tests against the real MongoDB, with a fake provider.

Assessments are produced by the real orchestrator (with faked engines, as in
``test_assessments_api.py``), so the analysis always reads genuinely
normalized evidence. No test here touches the network or needs a key.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.engines.ai.provider import AIProviderError, ProviderErrorCategory
from app.engines.qa.models import QaRunOutcome
from app.engines.qa.models import RunStatus as QaRunStatus
from app.engines.security.models import RunStatus as SecurityRunStatus
from app.engines.security.models import SecurityRunOutcome
from tests.ai_fakes import FakeProvider, grounded_answer
from tests.test_assessments_api import (
    FakeQaEngine,
    FakeSecurityEngine,
    _override_with,
    qa_outcome,
    security_outcome,
)

pytestmark = pytest.mark.integration

MISSING_ID = "0" * 24


# --- fixtures ------------------------------------------------------------------


@pytest.fixture
def cleanup(settings) -> Iterator[dict[str, list[str]]]:
    created: dict[str, list[str]] = {"targets": [], "assessments": [], "qa_runs": [], "security_runs": []}
    try:
        yield created
    finally:
        from bson import ObjectId
        from pymongo import MongoClient

        with MongoClient(settings.mongodb_uri) as direct:
            db = direct[settings.mongodb_database]
            ids = created["assessments"]
            if ids:
                db["ai_analysis_logs"].delete_many({"assessment_id": {"$in": ids}})
                db["evidence"].delete_many({"assessment_id": {"$in": ids}})
            for collection in ("assessments", "qa_runs", "security_runs", "targets"):
                if created[collection]:
                    db[collection].delete_many(
                        {"_id": {"$in": [ObjectId(i) for i in created[collection]]}}
                    )


def run_assessment(client: TestClient, cleanup, qa=None, security=None) -> dict[str, Any]:
    """A real orchestrated assessment (fake engines) for a fresh target."""
    from uuid import uuid4

    from app.api.dependencies import get_assessment_service

    target = client.post(
        "/targets",
        json={
            "name": f"pytest-ai-target-{uuid4().hex[:10]}",
            "base_url": "http://target.invalid:9999",
            "api_url": "http://target.invalid:9998",
            "type": "web_and_api",
            "enabled": True,
        },
    ).json()
    cleanup["targets"].append(target["id"])

    _override_with(
        client,
        qa or FakeQaEngine(qa_outcome()),
        security or FakeSecurityEngine(security_outcome()),
    )
    try:
        body = client.post("/assessments", json={"target_id": target["id"]}).json()
    finally:
        client.app.dependency_overrides.pop(get_assessment_service, None)

    cleanup["assessments"].append(body["id"])
    for key, collection in (("qa_run_id", "qa_runs"), ("security_run_id", "security_runs")):
        if body.get(key):
            cleanup[collection].append(body[key])
    return body


@pytest.fixture
def use_provider(client: TestClient) -> Iterator:
    from app.api.dependencies import get_ai_provider

    def install(provider) -> Any:
        client.app.dependency_overrides[get_ai_provider] = lambda: provider
        return provider

    try:
        yield install
    finally:
        client.app.dependency_overrides.pop(get_ai_provider, None)


def analyze(client: TestClient, assessment_id: str, **kwargs):
    return client.post(f"/assessments/{assessment_id}/ai-analysis", **kwargs)


def db(settings):
    from pymongo import MongoClient

    mongo = MongoClient(settings.mongodb_uri, tz_aware=True)
    return mongo, mongo[settings.mongodb_database]


TECHNICAL_FIELDS = (
    "target_id", "target_name", "summary", "qa_run_id", "security_run_id", "qa_status",
    "security_status", "qa_run_status", "security_run_status", "partial", "evidence_count",
    "started_at", "finished_at", "duration_ms", "security_coverage", "error",
)


# --- the happy path --------------------------------------------------------------


def test_analysis_completes_and_every_finding_points_at_this_assessments_evidence(
    client, cleanup, use_provider
) -> None:
    provider = use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)

    response = analyze(client, assessment["id"])
    assert response.status_code == 201, response.text
    analysis = response.json()

    assert analysis["status"] == "completed"
    assert analysis["provider"] == "fake" and analysis["model"] == "fake-model"
    assert analysis["analysis_version"] == "1.0"
    assert analysis["error"] is None
    assert "raw_response" not in analysis

    evidence = client.get(f"/assessments/{assessment['id']}/evidence").json()
    by_id = {item["evidence_id"]: item for item in evidence}
    assert sorted(analysis["evidence_ids"]) == sorted(by_id)
    assert analysis["evidence_count"] == len(evidence) == 4

    findings = analysis["result"]["findings"]
    assert findings, "the fake provider reports the failed check and the scanner findings"
    for item in findings:
        assert item["evidence_ids"], item
        for evidence_id, ref in zip(item["evidence_ids"], item["evidence_refs"]):
            record = by_id[evidence_id]  # KeyError == an ungrounded finding
            assert ref == f"EV-{record['sequence'] + 1:03d}"
            assert record["assessment_id"] == assessment["id"]
        assert item["affected_components"] == list(
            dict.fromkeys(by_id[e]["target_component"] for e in item["evidence_ids"])
        )
    assert len(provider.calls) == 1


def test_the_technical_assessment_is_untouched_and_goes_through_analyzing(
    client, cleanup, use_provider
) -> None:
    use_provider(FakeProvider())
    before = run_assessment(client, cleanup)
    analysis = analyze(client, before["id"]).json()

    after = client.get(f"/assessments/{before['id']}").json()
    for field in TECHNICAL_FIELDS:
        assert after[field] == before[field], field
    assert after["status"] == "completed"
    assert after["ai_analysis_status"] == "completed"
    assert after["ai_analysis_id"] == analysis["analysis_id"]

    states = [t["state"] for t in after["state_history"]]
    assert states[-3:] == ["completed", "analyzing", "completed"]
    assert analysis["analysis_id"] in after["state_history"][-1]["message"]
    # The Phase 4 history before it is exactly as it was.
    assert after["state_history"][: len(before["state_history"])] == before["state_history"]


def test_get_returns_status_latest_and_latest_completed(client, cleanup, use_provider) -> None:
    use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)

    view = client.get(f"/assessments/{assessment['id']}/ai-analysis").json()
    assert view == {
        "assessment_id": assessment["id"], "status": "not_analyzed",
        "latest": None, "latest_completed": None,
    }

    created = analyze(client, assessment["id"]).json()
    view = client.get(f"/assessments/{assessment['id']}/ai-analysis").json()
    assert view["status"] == "completed"
    assert view["latest"] == view["latest_completed"] == created


def test_repeated_analysis_keeps_every_execution(client, cleanup, use_provider, settings) -> None:
    use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)

    first = analyze(client, assessment["id"]).json()
    second = analyze(client, assessment["id"]).json()
    assert first["analysis_id"] != second["analysis_id"]

    history = client.get(f"/assessments/{assessment['id']}/ai-analysis/history").json()
    assert [h["analysis_id"] for h in history] == [second["analysis_id"], first["analysis_id"]]
    assert history[1] == first  # the earlier record was not overwritten
    view = client.get(f"/assessments/{assessment['id']}/ai-analysis").json()
    assert view["latest"]["analysis_id"] == second["analysis_id"]

    mongo, database = db(settings)
    with mongo:
        assert database["ai_analysis_logs"].count_documents({"assessment_id": assessment["id"]}) == 2


# --- provider failures ---------------------------------------------------------------


def _assert_failed_and_assessment_intact(client, assessment, category: str) -> dict[str, Any]:
    view = client.get(f"/assessments/{assessment['id']}/ai-analysis").json()
    assert view["status"] == "failed"
    failed = view["latest"]
    assert failed["result"] is None
    assert failed["error"]["category"] == category
    after = client.get(f"/assessments/{assessment['id']}").json()
    assert after["status"] == "completed"
    assert after["ai_analysis_status"] == "failed"
    for field in TECHNICAL_FIELDS:
        assert after[field] == assessment[field], field
    return failed


@pytest.mark.parametrize(
    ("category", "http_status"),
    [
        (ProviderErrorCategory.RATE_LIMIT, 502),
        (ProviderErrorCategory.TIMEOUT, 502),
        (ProviderErrorCategory.AUTHENTICATION, 502),
        (ProviderErrorCategory.INVALID_MODEL, 502),
        (ProviderErrorCategory.NETWORK, 502),
        (ProviderErrorCategory.CONFIGURATION, 503),
    ],
)
def test_provider_failure_is_recorded_and_never_harms_the_assessment(
    client, cleanup, use_provider, category, http_status
) -> None:
    use_provider(FakeProvider(error=AIProviderError(category, f"simulated {category.value}")))
    assessment = run_assessment(client, cleanup)

    response = analyze(client, assessment["id"])
    assert response.status_code == http_status, response.text
    failed = _assert_failed_and_assessment_intact(client, assessment, category.value)
    assert failed["analysis_id"] in response.json()["detail"]
    assert failed["error"]["message"] == f"simulated {category.value}"


def test_an_unexpected_provider_exception_is_a_recorded_failure(client, cleanup, use_provider) -> None:
    use_provider(FakeProvider(error=RuntimeError("provider bug")))
    assessment = run_assessment(client, cleanup)
    assert analyze(client, assessment["id"]).status_code == 502
    _assert_failed_and_assessment_intact(client, assessment, "provider_error")
    # The lock was released: analysis can be retried straight away.
    use_provider(FakeProvider())
    assert analyze(client, assessment["id"]).status_code == 201


# --- rejected answers --------------------------------------------------------------


def test_invalid_json_is_rejected_and_kept_for_audit(client, cleanup, use_provider, settings) -> None:
    use_provider(FakeProvider(respond=lambda _: "Sure! Here is my analysis: everything is fine."))
    assessment = run_assessment(client, cleanup)

    assert analyze(client, assessment["id"]).status_code == 502
    failed = _assert_failed_and_assessment_intact(client, assessment, "invalid_json")
    assert "raw_response" not in failed

    mongo, database = db(settings)
    with mongo:
        stored = database["ai_analysis_logs"].find_one({"analysis_id": failed["analysis_id"]})
    assert stored["raw_response"].startswith("Sure!")
    assert stored["status"] == "failed"


def test_an_unknown_evidence_reference_fails_the_whole_analysis(client, cleanup, use_provider) -> None:
    def hallucinate(user: str) -> str:
        data = grounded_answer(user)
        data["findings"][0]["evidence_ids"].append("EV-999")
        return json.dumps(data)

    use_provider(FakeProvider(respond=hallucinate))
    assessment = run_assessment(client, cleanup)
    assert analyze(client, assessment["id"]).status_code == 502
    failed = _assert_failed_and_assessment_intact(client, assessment, "unknown_evidence_reference")
    assert failed["error"]["details"]["unknown"] == ["EV-999"]


def test_evidence_from_another_assessment_is_rejected(client, cleanup, use_provider) -> None:
    use_provider(FakeProvider())
    other = run_assessment(client, cleanup)
    foreign_id = client.get(f"/assessments/{other['id']}/evidence").json()[0]["evidence_id"]

    def borrow(user: str) -> str:
        data = grounded_answer(user)
        data["findings"][0]["evidence_ids"] = [foreign_id]
        return json.dumps(data)

    use_provider(FakeProvider(respond=borrow))
    assessment = run_assessment(client, cleanup)
    assert analyze(client, assessment["id"]).status_code == 502
    _assert_failed_and_assessment_intact(client, assessment, "cross_assessment_reference")


@pytest.mark.parametrize(
    ("mutate", "category"),
    [
        (lambda d: d["findings"][0].update(confidence="certain"), "schema_violation"),
        (lambda d: d["findings"][0].update(type="correlation"), "schema_violation"),
        (lambda d: d["findings"][1].update(tool_severity="critical"), "schema_violation"),
        (lambda d: d["findings"][1].update(tool_severity="high"), "unsupported_severity"),
        (lambda d: d["findings"][0].pop("evidence_ids"), "schema_violation"),
        (lambda d: d["findings"][0].update(risk_score=10), "schema_violation"),
    ],
)
def test_invalid_answers_are_never_saved_as_completed(
    client, cleanup, use_provider, mutate, category
) -> None:
    def respond(user: str) -> str:
        data = grounded_answer(user)
        mutate(data)
        return json.dumps(data)

    use_provider(FakeProvider(respond=respond))
    assessment = run_assessment(client, cleanup)
    assert analyze(client, assessment["id"]).status_code == 502
    _assert_failed_and_assessment_intact(client, assessment, category)


# --- eligibility and errors --------------------------------------------------------


def test_missing_and_malformed_assessment_ids(client, use_provider) -> None:
    use_provider(FakeProvider())
    assert analyze(client, MISSING_ID).status_code == 404
    assert analyze(client, "nope").status_code == 400
    assert client.get(f"/assessments/{MISSING_ID}/ai-analysis").status_code == 404
    assert client.get("/assessments/nope/ai-analysis").status_code == 400
    assert client.get(f"/assessments/{MISSING_ID}/ai-analysis/history").status_code == 404


def test_an_assessment_without_evidence_is_404(client, cleanup, use_provider) -> None:
    provider = use_provider(FakeProvider())
    now = datetime.now(timezone.utc)
    empty_qa = QaRunOutcome(status=QaRunStatus.PASSED, started_at=now, finished_at=now, duration_ms=1)
    empty_security = SecurityRunOutcome(
        status=SecurityRunStatus.COMPLETED, started_at=now, finished_at=now, duration_ms=1
    )
    assessment = run_assessment(
        client, cleanup, FakeQaEngine(empty_qa), FakeSecurityEngine(empty_security)
    )
    assert assessment["status"] == "completed" and assessment["evidence_count"] == 0

    response = analyze(client, assessment["id"])
    assert response.status_code == 404
    assert "no normalized evidence" in response.json()["detail"]
    assert provider.calls == []


def test_a_failed_assessment_is_not_analyzable(client, cleanup, use_provider) -> None:
    provider = use_provider(FakeProvider())
    assessment = run_assessment(
        client, cleanup,
        FakeQaEngine(exc=RuntimeError("no browser")),
        FakeSecurityEngine(exc=RuntimeError("no scanner")),
    )
    assert assessment["status"] == "failed"
    assert analyze(client, assessment["id"]).status_code == 409
    assert provider.calls == []


def test_a_running_analysis_blocks_a_second_one(client, cleanup, use_provider, settings) -> None:
    from bson import ObjectId

    provider = use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)
    mongo, database = db(settings)
    with mongo:
        database["assessments"].update_one(
            {"_id": ObjectId(assessment["id"])},
            {"$set": {"status": "analyzing", "updated_at": datetime.now(timezone.utc)}},
        )
    assert analyze(client, assessment["id"]).status_code == 409
    assert provider.calls == []


def test_an_abandoned_analysis_does_not_lock_the_assessment_forever(
    client, cleanup, use_provider, settings
) -> None:
    from bson import ObjectId

    use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    mongo, database = db(settings)
    with mongo:
        database["assessments"].update_one(
            {"_id": ObjectId(assessment["id"])},
            {"$set": {"status": "analyzing", "updated_at": long_ago}},
        )
        database["ai_analysis_logs"].insert_one(
            {"analysis_id": "abandoned-one", "assessment_id": assessment["id"], "provider": "fake",
             "model": "fake-model", "analysis_version": "1.0", "status": "running",
             "created_at": long_ago}
        )

    assert analyze(client, assessment["id"]).status_code == 201

    mongo, database = db(settings)  # the first client was closed by its with-block
    with mongo:
        abandoned = database["ai_analysis_logs"].find_one({"analysis_id": "abandoned-one"})
        stored = database["assessments"].find_one({"_id": ObjectId(assessment["id"])})
    assert abandoned["status"] == "failed" and abandoned["error"]["category"] == "abandoned"
    assert [t["state"] for t in stored["state_history"]][-3:] == ["completed", "analyzing", "completed"]
    assert stored["status"] == "completed"


def test_the_client_cannot_submit_evidence(client, cleanup, use_provider) -> None:
    provider = use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)
    response = analyze(client, assessment["id"], json={"evidence": [{"id": "EV-001", "actual": "x"}]})
    assert response.status_code == 422
    assert provider.calls == []
    # An empty body is fine.
    assert analyze(client, assessment["id"], json={}).status_code == 201


# --- what reaches the provider, and what reaches the logs -------------------------


def test_the_prompt_carries_evidence_but_no_secrets_or_internals(
    client, cleanup, use_provider, settings
) -> None:
    provider = use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)
    analyze(client, assessment["id"])

    (call,) = provider.calls
    prompt = call["system"] + call["user"]
    assert "BEGIN ASSESSMENT EVIDENCE" in call["user"]
    assert "BEGIN ASSESSMENT EVIDENCE" not in call["system"]
    for leak in (settings.mongodb_uri, "evidence_payload", "source_run_id",
                 assessment["qa_run_id"], assessment["security_run_id"]):
        assert leak not in prompt, leak
    if settings.zap_api_key:
        assert settings.zap_api_key not in prompt
    if settings.openai_api_key:
        assert settings.openai_api_key not in prompt


def test_logs_carry_metadata_not_prompts(client, cleanup, use_provider, caplog) -> None:
    use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)
    with caplog.at_level(logging.DEBUG):
        analysis = analyze(client, assessment["id"]).json()

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert analysis["analysis_id"] in text
    for fragment in ("BEGIN ASSESSMENT EVIDENCE", "evidence-grounded QA", "Page title is missing"):
        assert fragment not in text


# --- persistence -------------------------------------------------------------------


def test_the_analysis_really_is_in_mongodb(client, cleanup, use_provider, settings) -> None:
    use_provider(FakeProvider())
    assessment = run_assessment(client, cleanup)
    analysis = analyze(client, assessment["id"]).json()

    mongo, database = db(settings)
    with mongo:
        stored = database["ai_analysis_logs"].find_one({"analysis_id": analysis["analysis_id"]})
        indexes = database["ai_analysis_logs"].index_information()
        cited = {e for f in stored["result"]["findings"] for e in f["evidence_ids"]}
        owned = database["evidence"].count_documents(
            {"evidence_id": {"$in": sorted(cited)}, "assessment_id": assessment["id"]}
        )

    for field in ("assessment_id", "provider", "model", "analysis_version", "status",
                  "evidence_ids", "result", "created_at", "started_at", "completed_at"):
        assert stored.get(field) is not None, field
    assert stored["status"] == "completed"
    assert hasattr(stored["created_at"], "year")
    assert owned == len(cited) > 0
    assert indexes["ai_analysis_by_assessment"]["key"] == [("assessment_id", 1), ("created_at", -1)]
    assert not indexes["ai_analysis_by_assessment"].get("unique", False)
