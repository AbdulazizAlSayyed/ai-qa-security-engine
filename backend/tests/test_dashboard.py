"""Phase 7 focused tests: dashboard aggregation and API.

The aggregation tests run DashboardService against an isolated, throwaway
database with hand-made documents, so every expected number is exact. The
API tests use the real app (and, for one case, a real orchestrated
assessment with fake engines, cleaned up afterwards).
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.errors import ServerSelectionTimeoutError

from app.services.dashboard_service import DashboardService
from tests.test_ai_analysis_api import cleanup, run_assessment  # noqa: F401 - fixtures
from tests.test_correlation_api import derived_cleanup  # noqa: F401 - fixture

#: Noon UTC today, so "N days ago" never straddles a UTC day boundary.
NOW = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


def assessment(days_ago: int, status: str = "completed", **fields: Any) -> dict[str, Any]:
    created = NOW - timedelta(days=days_ago, minutes=fields.pop("minutes", 0))
    doc = {
        "_id": ObjectId(),
        "target_id": "t1",
        "target_name": "Target One",
        "status": status,
        "partial": False,
        "created_at": created,
        "started_at": created,
        "finished_at": created + timedelta(seconds=5),
        "duration_ms": 5000,
        "qa_status": "completed",
        "security_status": "completed",
        "summary": {
            "qa": {"total": 5, "passed": 4, "failed": 1, "skipped": 0, "error": 0},
            "security": {"total": 3, "high": 1, "medium": 1, "low": 0, "informational": 1},
            "total_findings": 4,
            "evidence_total": 8,
        },
        "evidence_count": 8,
        "ai_analysis_status": "not_analyzed",
    }
    doc.update(fields)
    return doc


def issue(assessment_id: ObjectId, number: int, priority: str, type_: str = "security") -> dict:
    return {
        "assessment_id": str(assessment_id),
        "group_key": f"k{number}",
        "issue_id": f"ISSUE-{number:03d}",
        "issue_number": number,
        "priority": priority,
        "priority_score": 50,
        "type": type_,
    }


def run_service(settings, documents: dict[str, list[dict]], **kwargs) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True, serverSelectionTimeoutMS=3000)
        name = f"ai_qa_security_p7test_{uuid4().hex[:10]}"
        try:
            db = client[name]
            for collection, docs in documents.items():
                if docs:
                    await db[collection].insert_many(docs)
            return await DashboardService(db).overview(**kwargs)
        finally:
            await client.drop_database(name)
            await client.close()

    try:
        return asyncio.run(go())
    except ServerSelectionTimeoutError:  # pragma: no cover - environment
        pytest.skip("MongoDB is not reachable")


# --- aggregation ------------------------------------------------------------------


def test_empty_database_gives_zeros_not_errors(settings) -> None:
    result = run_service(settings, {})
    assert result["assessments"]["total"] == 0
    assert result["issues"]["by_priority"] == {"total": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0}
    assert result["qa"]["failed"] == 0 and result["security"]["total"] == 0
    assert result["history"] == [] and result["trends"] == [] and result["latest"] is None
    assert result["targets"] == {"total": 0, "enabled": 0}


def test_counts_history_latest_and_trends_are_exact(settings) -> None:
    a_old = assessment(3)
    a_partial = assessment(1, partial=True, qa_status="failed", ai_analysis_status="completed",
                           correlation={"status": "completed"})
    a_failed = assessment(1, status="failed", minutes=5, summary={})
    a_running = assessment(0, status="qa_running", summary={})
    a_outside = assessment(40)
    issues = [
        issue(a_partial["_id"], 1, "P1"),
        issue(a_partial["_id"], 2, "P2", "qa"),
        issue(a_partial["_id"], 3, "P2"),
        issue(a_old["_id"], 1, "P4"),
    ]
    targets = [{"name": "t", "enabled": True}, {"name": "u", "enabled": False}]
    result = run_service(
        settings,
        {"assessments": [a_old, a_partial, a_failed, a_running, a_outside], "issues": issues,
         "targets": targets},
        history_limit=3,
        trend_days=30,
    )

    counts = result["assessments"]
    assert counts["total"] == 5
    assert counts["completed"] == 3 and counts["failed"] == 1 and counts["running"] == 1
    assert counts["partial"] == 1 and counts["ai_analyzed"] == 1 and counts["correlated"] == 1
    assert counts["by_status"] == {"completed": 3, "failed": 1, "qa_running": 1}
    # Sums of the stored summaries; assessments without a summary add nothing.
    assert result["qa"] == {"total": 15, "passed": 12, "failed": 3, "skipped": 0, "error": 0}
    assert result["security"] == {"total": 9, "high": 3, "medium": 3, "low": 0, "informational": 3}
    assert result["issues"]["by_priority"] == {"total": 4, "P1": 1, "P2": 2, "P3": 0, "P4": 1}
    assert result["issues"]["by_type"] == {"qa": 1, "security": 3}
    assert result["issues"]["assessments_with_issues"] == 2
    assert result["targets"] == {"total": 2, "enabled": 1}

    # History: newest first by created_at, limited, with each assessment's own issues.
    ids = [item["id"] for item in result["history"]]
    assert ids == [str(a_running["_id"]), str(a_partial["_id"]), str(a_failed["_id"])]
    partial_item = result["history"][1]
    assert partial_item["issues"] == {"total": 3, "P1": 1, "P2": 2, "P3": 0, "P4": 0}
    assert partial_item["partial"] is True and partial_item["qa_status"] == "failed"
    assert partial_item["correlation_status"] == "completed"
    assert result["history"][0]["correlation_status"] == "not_correlated"

    # Latest = newest assessment whose technical result is final.
    assert result["latest"]["id"] == str(a_partial["_id"])

    # Trends: only days with assessments inside the window, oldest first.
    days = [point["date"] for point in result["trends"]]
    assert days == sorted(days) and len(days) == 3
    one_day_ago = next(p for p in result["trends"] if p["assessments"] == 2)
    assert one_day_ago["completed"] == 1 and one_day_ago["failed"] == 1
    assert one_day_ago["partial"] == 1 and one_day_ago["qa_failed"] == 1
    assert one_day_ago["issues"] == {"total": 3, "P1": 1, "P2": 2, "P3": 0, "P4": 0}
    assert sum(p["assessments"] for p in result["trends"]) == 4  # the 40-day-old one is outside


# --- API ----------------------------------------------------------------------------------


def test_dashboard_endpoint_shape_and_validation(client) -> None:
    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["history_limit"] == 20 and body["trend_days"] == 30
    for key in ("assessments", "qa", "security", "issues", "history", "trends", "targets"):
        assert key in body
    for params in ({"history_limit": 0}, {"history_limit": 101}, {"trend_days": 0},
                   {"trend_days": 366}, {"trend_days": "abc"}):
        assert client.get("/dashboard", params=params).status_code == 422, params


def test_dashboard_reflects_a_real_correlated_assessment(client, derived_cleanup) -> None:
    created = run_assessment(client, derived_cleanup)
    assert client.post(f"/assessments/{created['id']}/correlation").status_code == 200
    issues = client.get(f"/assessments/{created['id']}/issues").json()

    body = client.get("/dashboard", params={"history_limit": 100}).json()
    item = next(h for h in body["history"] if h["id"] == created["id"])
    assert item["correlation_status"] == "completed"
    assert item["issues"]["total"] == len(issues)
    for level in ("P1", "P2", "P3", "P4"):
        assert item["issues"][level] == sum(1 for i in issues if i["priority"] == level)
    assert item["qa"] == {k: created["summary"]["qa"][k] for k in item["qa"]}
    assert item["security"] == {k: created["summary"]["security"][k] for k in item["security"]}


def test_database_failure_is_a_generic_500(client) -> None:
    from pymongo.errors import OperationFailure

    from app.api.dependencies import get_dashboard_service

    class BrokenCollection:
        async def aggregate(self, *_args, **_kwargs):
            raise OperationFailure("secret internal detail mongodb://user:pass@host")

    class BrokenService(DashboardService):
        def __init__(self) -> None:
            self._assessments = self._issues = self._targets = BrokenCollection()

    client.app.dependency_overrides[get_dashboard_service] = BrokenService
    try:
        response = client.get("/dashboard")
    finally:
        client.app.dependency_overrides.pop(get_dashboard_service, None)
    assert response.status_code == 500
    text = response.text
    assert "secret" not in text and "mongodb://" not in text and "OperationFailure" not in text


# --- guardrails ------------------------------------------------------------------------------

APP = Path(__file__).resolve().parents[1] / "app"
PHASE7_FILES = [
    APP / "services" / "dashboard_service.py",
    APP / "api" / "routes" / "dashboard.py",
    APP / "schemas" / "dashboard.py",
]


@pytest.mark.parametrize("path", PHASE7_FILES, ids=lambda p: p.name)
def test_dashboard_is_read_only_and_calls_nothing_external(path: Path) -> None:
    source = path.read_text(encoding="utf-8-sig")
    imports = "\n".join(re.findall(r"^\s*(?:from|import)\s+[\w.]+", source, re.MULTILINE))
    for banned in ("openai", "app.engines.ai", "app.engines.correlation",
                   "app.engines.prioritization", "subprocess", "httpx", "requests"):
        assert banned not in imports, f"{path.name} imports {banned}"
    for call in ("eval(", "exec(", "os.system(", "insert_", "update_", "delete_", "replace_one"):
        assert call not in source, f"{path.name} uses {call}"
    assert "raw_response" not in source
