"""Dashboard aggregation (Phase 7). Read-only.

    Route -> DashboardService -> MongoDB aggregation over
             assessments, issues, targets

A consumer of what Phases 1-6 persisted - it owns no data. Every count is
computed by MongoDB on request, with projections, so the dashboard always
shows the stored state and nothing is cached or duplicated:

* assessment counts, QA and security totals: one ``$facet`` over
  ``assessments`` (summing the deterministic ``summary`` Phase 4 wrote);
* issue counts: one ``$facet`` over ``issues`` (the Phase 6 ``priority`` and
  ``type`` as stored - no re-scoring);
* history and ``latest``: ``assessments`` newest first, each joined to its
  own issues' priority counts with a ``$lookup`` that uses the existing
  ``issues_by_priority`` index prefix ``(assessment_id, ...)``;
* trends: assessments created in the last ``trend_days`` days, grouped by
  UTC calendar day of the stored ``created_at``. Days without an assessment
  are omitted, not filled with zeros.

Timestamps are the BSON dates the platform already stores (UTC).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.engines.orchestrator.state_machine import utc_now
from app.models import assessment as assessment_model
from app.models import issue as issue_model
from app.models import target as target_model

DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100
DEFAULT_TREND_DAYS = 30
MAX_TREND_DAYS = 365

#: The Phase 4 states a pipeline passes through while it is still working.
ACTIVE_STATES = ("created", "running", "qa_running", "security_running", "normalizing")
#: States whose technical result is final (analyzing = completed + AI running).
FINAL_OK_STATES = ("completed", "analyzing")
PRIORITIES = ("P1", "P2", "P3", "P4")
QA_KEYS = ("total", "passed", "failed", "skipped", "error")
SECURITY_KEYS = ("total", "high", "medium", "low", "informational")


class DashboardPersistenceError(Exception):
    """MongoDB could not answer the aggregation (500, generic message)."""


def _count_by_priority_lookup() -> dict[str, Any]:
    """Join each assessment to the priority counts of its own issues."""
    group: dict[str, Any] = {"_id": None, "total": {"$sum": 1}}
    for level in PRIORITIES:
        group[level] = {"$sum": {"$cond": [{"$eq": ["$priority", level]}, 1, 0]}}
    return {
        "$lookup": {
            "from": issue_model.COLLECTION_NAME,
            "let": {"aid": {"$toString": "$_id"}},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$assessment_id", "$$aid"]}}},
                {"$project": {"priority": 1}},
                {"$group": group},
            ],
            "as": "issue_counts",
        }
    }


_HISTORY_PROJECTION = {
    "target_id": 1,
    "target_name": 1,
    "status": 1,
    "partial": 1,
    "created_at": 1,
    "started_at": 1,
    "finished_at": 1,
    "duration_ms": 1,
    "qa_status": 1,
    "security_status": 1,
    "summary": 1,
    "evidence_count": 1,
    "ai_analysis_status": 1,
    "correlation.status": 1,
}


def _counts(source: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, int]:
    source = source or {}
    return {key: int(source.get(key) or 0) for key in keys}


def _history_item(document: dict[str, Any]) -> dict[str, Any]:
    summary = document.get("summary") or {}
    issue_counts = (document.get("issue_counts") or [{}])[0]
    return {
        "id": str(document["_id"]),
        "target_id": str(document.get("target_id") or ""),
        "target_name": str(document.get("target_name") or ""),
        "status": document.get("status"),
        "partial": bool(document.get("partial", False)),
        "created_at": document.get("created_at"),
        "started_at": document.get("started_at"),
        "finished_at": document.get("finished_at"),
        "duration_ms": document.get("duration_ms"),
        "qa_status": document.get("qa_status") or "pending",
        "security_status": document.get("security_status") or "pending",
        "qa": _counts(summary.get("qa"), QA_KEYS),
        "security": _counts(summary.get("security"), SECURITY_KEYS),
        "total_findings": int(summary.get("total_findings") or 0),
        "evidence_count": int(document.get("evidence_count") or 0),
        "ai_analysis_status": document.get("ai_analysis_status") or "not_analyzed",
        "correlation_status": (document.get("correlation") or {}).get("status") or "not_correlated",
        "issues": _counts(issue_counts, ("total", *PRIORITIES)),
    }


class DashboardService:
    def __init__(self, db: AsyncDatabase) -> None:
        self._assessments = assessment_model.get_collection(db)
        self._issues = issue_model.get_collection(db)
        self._targets = target_model.get_collection(db)

    async def overview(
        self,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        trend_days: int = DEFAULT_TREND_DAYS,
    ) -> dict[str, Any]:
        now = utc_now()
        try:
            totals = await self._assessment_totals()
            issues = await self._issue_totals()
            targets = await self._target_totals()
            history = await self._history({}, history_limit)
            latest = await self._history({"status": {"$in": list(FINAL_OK_STATES)}}, 1)
            trends = await self._trends(now - timedelta(days=trend_days))
        except PyMongoError as exc:
            # Never leak driver internals; the type name is enough for the log.
            raise DashboardPersistenceError(
                f"Dashboard data could not be read ({type(exc).__name__})."
            ) from exc

        return {
            "generated_at": now,
            "trend_days": trend_days,
            "history_limit": history_limit,
            "targets": targets,
            "assessments": totals["assessments"],
            "qa": totals["qa"],
            "security": totals["security"],
            "issues": issues,
            "latest": latest[0] if latest else None,
            "history": history,
            "trends": trends,
        }

    # --- aggregations -----------------------------------------------------------

    async def _assessment_totals(self) -> dict[str, Any]:
        sums: dict[str, Any] = {"_id": None}
        for key in QA_KEYS:
            sums[f"qa_{key}"] = {"$sum": f"$summary.qa.{key}"}
        for key in SECURITY_KEYS:
            sums[f"sec_{key}"] = {"$sum": f"$summary.security.{key}"}
        pipeline = [
            {
                "$project": {
                    "status": 1,
                    "partial": 1,
                    "summary": 1,
                    "ai_analysis_status": 1,
                    "correlation.status": 1,
                }
            },
            {
                "$facet": {
                    "by_status": [{"$group": {"_id": "$status", "n": {"$sum": 1}}}],
                    "flags": [
                        {
                            "$group": {
                                "_id": None,
                                "partial": {"$sum": {"$cond": [{"$eq": ["$partial", True]}, 1, 0]}},
                                "ai_analyzed": {
                                    "$sum": {
                                        "$cond": [{"$eq": ["$ai_analysis_status", "completed"]}, 1, 0]
                                    }
                                },
                                "correlated": {
                                    "$sum": {
                                        "$cond": [{"$eq": ["$correlation.status", "completed"]}, 1, 0]
                                    }
                                },
                            }
                        }
                    ],
                    "sums": [{"$group": sums}],
                }
            },
        ]
        result = await (await self._assessments.aggregate(pipeline)).to_list(length=None)
        facet = result[0] if result else {}
        by_status = {str(row["_id"]): int(row["n"]) for row in facet.get("by_status", [])}
        flags = (facet.get("flags") or [{}])[0]
        sums_row = (facet.get("sums") or [{}])[0]
        return {
            "assessments": {
                "total": sum(by_status.values()),
                "by_status": dict(sorted(by_status.items())),
                "completed": by_status.get("completed", 0),
                "failed": by_status.get("failed", 0),
                "running": sum(by_status.get(state, 0) for state in ACTIVE_STATES),
                "analyzing": by_status.get("analyzing", 0),
                "partial": int(flags.get("partial") or 0),
                "ai_analyzed": int(flags.get("ai_analyzed") or 0),
                "correlated": int(flags.get("correlated") or 0),
            },
            "qa": {key: int(sums_row.get(f"qa_{key}") or 0) for key in QA_KEYS},
            "security": {key: int(sums_row.get(f"sec_{key}") or 0) for key in SECURITY_KEYS},
        }

    async def _issue_totals(self) -> dict[str, Any]:
        pipeline = [
            {"$project": {"priority": 1, "type": 1, "assessment_id": 1}},
            {
                "$facet": {
                    "by_priority": [{"$group": {"_id": "$priority", "n": {"$sum": 1}}}],
                    "by_type": [{"$group": {"_id": "$type", "n": {"$sum": 1}}}],
                    "assessments": [{"$group": {"_id": "$assessment_id"}}, {"$count": "n"}],
                }
            },
        ]
        result = await (await self._issues.aggregate(pipeline)).to_list(length=None)
        facet = result[0] if result else {}
        by_priority = {str(row["_id"]): int(row["n"]) for row in facet.get("by_priority", [])}
        by_type = {str(row["_id"]): int(row["n"]) for row in facet.get("by_type", [])}
        assessments = (facet.get("assessments") or [{}])[0]
        return {
            "by_priority": {
                "total": sum(by_priority.values()),
                **{level: by_priority.get(level, 0) for level in PRIORITIES},
            },
            "by_type": dict(sorted(by_type.items())),
            "assessments_with_issues": int(assessments.get("n") or 0),
        }

    async def _target_totals(self) -> dict[str, int]:
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "enabled": {"$sum": {"$cond": [{"$eq": ["$enabled", True]}, 1, 0]}},
                }
            }
        ]
        result = await (await self._targets.aggregate(pipeline)).to_list(length=None)
        row = result[0] if result else {}
        return {"total": int(row.get("total") or 0), "enabled": int(row.get("enabled") or 0)}

    async def _history(self, match: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        pipeline = [
            {"$match": match},
            {"$sort": dict(assessment_model.LIST_SORT)},
            {"$limit": limit},
            {"$project": _HISTORY_PROJECTION},
            _count_by_priority_lookup(),
        ]
        documents = await (await self._assessments.aggregate(pipeline)).to_list(length=None)
        return [_history_item(document) for document in documents]

    async def _trends(self, since) -> list[dict[str, Any]]:
        group: dict[str, Any] = {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": "UTC"}},
            "assessments": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$in": ["$status", list(FINAL_OK_STATES)]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            "partial": {"$sum": {"$cond": [{"$eq": ["$partial", True]}, 1, 0]}},
            "qa_failed": {"$sum": "$summary.qa.failed"},
        }
        for key in SECURITY_KEYS:
            group[f"sec_{key}"] = {"$sum": f"$summary.security.{key}"}
        for key in ("total", *PRIORITIES):
            group[f"iss_{key}"] = {"$sum": {"$ifNull": [{"$first": f"$issue_counts.{key}"}, 0]}}

        pipeline = [
            {"$match": {"created_at": {"$gte": since}}},
            {"$project": {"created_at": 1, "status": 1, "partial": 1, "summary": 1}},
            _count_by_priority_lookup(),
            {"$group": group},
            {"$sort": {"_id": 1}},
        ]
        rows = await (await self._assessments.aggregate(pipeline)).to_list(length=None)
        return [
            {
                "date": str(row["_id"]),
                "assessments": int(row.get("assessments") or 0),
                "completed": int(row.get("completed") or 0),
                "failed": int(row.get("failed") or 0),
                "partial": int(row.get("partial") or 0),
                "qa_failed": int(row.get("qa_failed") or 0),
                "security": {key: int(row.get(f"sec_{key}") or 0) for key in SECURITY_KEYS},
                "issues": {key: int(row.get(f"iss_{key}") or 0) for key in ("total", *PRIORITIES)},
            }
            for row in rows
        ]
