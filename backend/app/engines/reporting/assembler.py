"""Report assembly (Phase 10): persisted records -> one normalized report model.

The model is a plain, JSON-serialisable dict built only from what Phases
1-9 stored. Nothing is recalculated: counts come from the assessment's
stored summary, priorities / scores / factors from the stored issues,
verdicts from the stored retests. Tool severity, AI confidence and issue
priority stay three separate fields and are never converted into each
other. Every free-text value passes through the Phase 5 redaction filter;
raw scanner payloads (``evidence_payload``, raw model text) are never
included.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.engines.ai.context import evidence_ref
from app.engines.reporting.redaction import clean, clean_list

REPORT_VERSION = "1.0"
PRIORITIES = ("P1", "P2", "P3", "P4")
#: QA evidence categories that are observations, not suite checks.
QA_OBSERVATION_CATEGORIES = {"client_errors": "console", "network": "network"}


def ts(value: Any) -> str | None:
    """UTC ISO-8601, second precision. Stored datetimes are UTC (naive or aware)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return clean(value, 64)


def _ref(evidence_by_id: dict[str, dict], eid: str) -> str:
    doc = evidence_by_id.get(str(eid))
    return evidence_ref(doc.get("sequence", 0)) if doc else str(eid)


def fingerprint(model: dict[str, Any]) -> str:
    """Identity of the *source data* a report shows (generation time excluded)."""
    body = {k: v for k, v in model.items() if k != "meta"}
    body["report_version"] = model["meta"]["report_version"]
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assemble(
    *,
    assessment: dict[str, Any],
    target: dict[str, Any] | None,
    qa_run: dict[str, Any] | None,
    security_run: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    retests: list[dict[str, Any]],
    traceability: dict[str, Any],
) -> dict[str, Any]:
    aid = str(assessment["_id"])
    ev_by_id = {str(e["evidence_id"]): e for e in evidence}
    evidence = sorted(evidence, key=lambda e: (e.get("sequence", 0), str(e.get("_id"))))

    # --- target: the assessment's snapshot is authoritative -------------------
    snapshot = {
        "target_id": str(assessment.get("target_id")),
        "name": clean(assessment.get("target_name"), 200),
        "base_url": clean(assessment.get("target_base_url"), 500),
        "api_url": clean(assessment.get("target_api_url"), 500),
        "type": clean(assessment.get("target_type"), 60),
        "source": "assessment snapshot",
    }
    registered = None
    if target is not None:
        registered = {
            "name": clean(target.get("name"), 200),
            "base_url": clean(target.get("base_url"), 500),
            "api_url": clean(target.get("api_url"), 500),
            "type": clean(target.get("type"), 60),
            "enabled": bool(target.get("enabled", True)),
        }
    snapshot["registered"] = registered
    snapshot["registry_differs"] = bool(
        registered
        and (registered["name"], registered["base_url"], registered["api_url"])
        != (snapshot["name"], snapshot["base_url"], snapshot["api_url"])
    )

    # --- pipeline ------------------------------------------------------------------
    pipeline = {
        "status": assessment.get("status"),
        "partial": bool(assessment.get("partial")),
        "created_at": ts(assessment.get("created_at")),
        "started_at": ts(assessment.get("started_at")),
        "finished_at": ts(assessment.get("finished_at")),
        "duration_ms": assessment.get("duration_ms"),
        "error": clean(assessment.get("error"), 1000),
        "stages": [
            {
                "stage": "qa",
                "status": assessment.get("qa_status"),
                "run_id": assessment.get("qa_run_id"),
                "run_status": assessment.get("qa_run_status"),
                "error": clean(assessment.get("qa_error"), 1000),
            },
            {
                "stage": "security",
                "status": assessment.get("security_status"),
                "run_id": assessment.get("security_run_id"),
                "run_status": assessment.get("security_run_status"),
                "error": clean(assessment.get("security_error"), 1000),
            },
        ],
        "state_history": [
            {"state": s.get("state"), "timestamp": ts(s.get("timestamp")), "message": clean(s.get("message"), 500)}
            for s in assessment.get("state_history") or []
        ],
    }

    # --- evidence (shared rows) ----------------------------------------------------
    def evidence_row(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "ref": evidence_ref(e.get("sequence", 0)),
            "evidence_id": str(e.get("evidence_id")),
            "source": e.get("source"),
            "finding_type": e.get("finding_type"),
            "category": clean(e.get("category"), 60),
            "title": clean(e.get("title"), 300),
            "target_component": clean(e.get("target_component"), 500),
            "status": e.get("status"),
            "tool_severity": e.get("tool_severity"),
            "expected": clean(e.get("expected"), 500),
            "actual": clean(e.get("actual"), 800),
            "source_run_id": e.get("source_run_id"),
            "source_finding_id": clean(e.get("source_finding_id"), 120),
        }

    rows = [evidence_row(e) for e in evidence]

    # --- QA: persisted run + its evidence ------------------------------------------
    qa_tests = (qa_run or {}).get("tests") or []
    qa_checks, qa_console, qa_network = [], [], []
    for e, row in zip(evidence, rows):
        if e.get("finding_type") != "qa":
            continue
        kind = QA_OBSERVATION_CATEGORIES.get(str(e.get("category")))
        if kind == "console":
            qa_console.append(row)
        elif kind == "network":
            qa_network.append(row)
        else:
            error = None
            fid = str(e.get("source_finding_id") or "")
            if fid.startswith("tests[") and fid.endswith("]") and fid[6:-1].isdigit():
                index = int(fid[6:-1])
                if index < len(qa_tests):
                    error = clean(qa_tests[index].get("error"), 800)
            qa_checks.append({**row, "error": error})
    qa = {
        "run_id": assessment.get("qa_run_id"),
        "run_status": assessment.get("qa_run_status"),
        "stage_status": assessment.get("qa_status"),
        "counts": (assessment.get("summary") or {}).get("qa") or {},
        "checks": qa_checks,
        "console_errors": qa_console,
        "network_failures": qa_network,
    }

    # --- security: coverage + components + evidence ----------------------------------
    components = []
    for c in (security_run or {}).get("components") or []:
        components.append(
            {
                "name": c.get("name"),
                "enabled": c.get("enabled"),
                "status": c.get("status"),
                "detail": clean(c.get("detail"), 500),
                "finding_count": len(c.get("findings") or []),
            }
        )
    security = {
        "run_id": assessment.get("security_run_id"),
        "run_status": assessment.get("security_run_status"),
        "stage_status": assessment.get("security_status"),
        "counts": (assessment.get("summary") or {}).get("security") or {},
        "coverage": [
            {"source": c.get("source"), "status": c.get("status"), "detail": clean(c.get("detail"), 500)}
            for c in assessment.get("security_coverage") or []
        ],
        "components": components,
        "findings": [r for r in rows if r["finding_type"] == "security"],
    }

    # --- AI analysis: latest completed, never re-run ---------------------------------
    ordered = sorted(analyses, key=lambda x: (ts(x.get("created_at")) or "", str(x.get("_id"))), reverse=True)
    completed = [x for x in ordered if x.get("status") == "completed" and x.get("result")]
    latest_attempt = ordered[0] if ordered else None
    ai: dict[str, Any] = {
        "status": assessment.get("ai_analysis_status") or "not_analyzed",
        "attempts": len(ordered),
        "failed_attempts": sum(1 for x in ordered if x.get("status") == "failed"),
        "latest_failure": None,
        "analysis": None,
    }
    if latest_attempt is not None and latest_attempt.get("status") == "failed":
        err = latest_attempt.get("error") or {}
        ai["latest_failure"] = {
            "analysis_id": latest_attempt.get("analysis_id"),
            "provider": latest_attempt.get("provider"),
            "model": clean(latest_attempt.get("model"), 100),
            "category": clean(err.get("category"), 60),
            "message": clean(err.get("message"), 500),
            "at": ts(latest_attempt.get("created_at")),
        }
    if completed:
        x = completed[0]
        result = x.get("result") or {}
        ai["analysis"] = {
            "analysis_id": x.get("analysis_id"),
            "provider": x.get("provider"),
            "model": clean(x.get("model"), 100),
            "analysis_version": x.get("analysis_version"),
            "status": x.get("status"),
            "completed_at": ts(x.get("completed_at")),
            "evidence_supplied": len(x.get("evidence_ids") or []),
            "overall_assessment": clean(result.get("overall_assessment"), 6000),
            "findings": [
                {
                    "finding_id": f.get("finding_id"),
                    "type": f.get("type"),
                    "status": f.get("status"),
                    "title": clean(f.get("title"), 300),
                    "description": clean(f.get("description"), 4000),
                    "impact": clean(f.get("impact"), 2000),
                    "confidence": f.get("confidence"),
                    "tool_severity": f.get("tool_severity"),
                    "evidence_refs": [_ref(ev_by_id, i) for i in f.get("evidence_ids") or []],
                    "affected_components": clean_list(f.get("affected_components"), 300),
                    "uncertainty": clean(f.get("uncertainty"), 2000),
                }
                for f in result.get("findings") or []
            ],
            "evidence_gaps": clean_list(result.get("evidence_gaps"), 1000),
            "limitations": clean_list(result.get("limitations"), 1000),
        }

    # --- correlation & prioritized issues (persisted Phase 6 values) -----------------
    corr = assessment.get("correlation") or None
    groups_sorted = sorted(groups, key=lambda g: g.get("group_number", 0))
    issues_sorted = sorted(issues, key=lambda i: i.get("issue_number", 0))
    group_by_id = {str(g.get("correlation_group_id")): g for g in groups_sorted}
    correlation = {
        "status": (corr or {}).get("status") or "not_run",
        "correlation_version": (corr or {}).get("correlation_version"),
        "priority_model_version": (corr or {}).get("priority_model_version"),
        "completed_at": ts((corr or {}).get("completed_at")),
        "ai_analysis_id": (corr or {}).get("ai_analysis_id"),
        "evidence_considered": (corr or {}).get("evidence_considered"),
        "error": clean((corr or {}).get("error"), 500),
        "groups": [
            {
                "correlation_group_id": g.get("correlation_group_id"),
                "correlation_rule": g.get("correlation_rule"),
                "correlation_reason": clean(g.get("correlation_reason"), 800),
                "finding_type": g.get("finding_type"),
                "tool_severity": g.get("tool_severity"),
                "evidence_refs": [_ref(ev_by_id, i) for i in g.get("evidence_ids") or []],
            }
            for g in groups_sorted
        ],
        "issues": [
            {
                "issue_id": i.get("issue_id"),
                "correlation_group_id": i.get("correlation_group_id"),
                "correlation_rule": i.get("correlation_rule"),
                "correlation_reason": clean(group_by_id.get(str(i.get("correlation_group_id")), {}).get("correlation_reason"), 800),
                "type": i.get("type"),
                "title": clean(i.get("title"), 300),
                "priority": i.get("priority"),
                "priority_score": i.get("priority_score"),
                "priority_model_version": i.get("priority_model_version"),
                "score_factors": [
                    {"factor": f.get("factor"), "points": f.get("points"), "detail": clean(f.get("detail"), 300)}
                    for f in i.get("score_factors") or []
                ],
                "priority_reasons": clean_list(i.get("priority_reasons"), 300),
                "tool_severity": i.get("tool_severity"),
                "ai_confidence": i.get("confidence"),
                "affected_components": clean_list(i.get("affected_components"), 300),
                "evidence_refs": [_ref(ev_by_id, x) for x in i.get("evidence_ids") or []],
                "ai_finding_ids": list(i.get("ai_finding_ids") or []),
            }
            for i in issues_sorted
        ],
    }

    # --- recommendations: newest set, advisory only ----------------------------------
    rec_summary = assessment.get("recommendation") or {}
    newest_set = None
    if recommendations:
        newest = max(recommendations, key=lambda r: (ts(r.get("updated_at")) or "", str(r.get("_id"))))
        newest_set = newest.get("ai_analysis_id")
    shown = sorted(
        [r for r in recommendations if r.get("ai_analysis_id") == newest_set],
        key=lambda r: r.get("recommendation_number", 0),
    )
    recs = {
        "status": rec_summary.get("status") or ("completed" if recommendations else "not_generated"),
        "ai_analysis_id": newest_set,
        "set_count": len({r.get("ai_analysis_id") for r in recommendations}),
        "items": [
            {
                "recommendation_id": r.get("recommendation_id"),
                "issue_id": r.get("issue_id"),
                "related_issue_ids": list(r.get("related_issue_ids") or []),
                "issue_priority": r.get("issue_priority"),
                "type": r.get("type"),
                "confidence": r.get("confidence"),
                "advisory_status": r.get("advisory_status") or "advisory",
                "title": clean(r.get("title"), 300),
                "description": clean(r.get("description"), 4000),
                "rationale": clean(r.get("rationale"), 2000),
                "affected_components": clean_list(r.get("affected_components"), 300),
                "evidence_refs": [_ref(ev_by_id, x) for x in r.get("evidence_ids") or []],
                "retest": _spec(r.get("retest") or {}, ev_by_id),
            }
            for r in shown
        ],
    }

    # --- retests: status and verdict kept apart -------------------------------------------
    retest_rows = []
    for t in sorted(retests, key=lambda x: x.get("retest_number", 0), reverse=True):
        summary = t.get("result_summary") or {}
        err = t.get("error") or {}
        retest_rows.append(
            {
                "retest_id": t.get("retest_id"),
                "recommendation_id": t.get("recommendation_id"),
                "issue_id": t.get("issue_id"),
                "type": t.get("type"),
                "scope": t.get("scope"),
                "target_component": clean(t.get("target_component"), 500),
                "pass_condition": t.get("pass_condition"),
                "status": t.get("status"),
                "verdict": t.get("verdict") if t.get("status") == "completed" else None,
                "outcome": retest_outcome(t),
                "started_at": ts(t.get("started_at")),
                "completed_at": ts(t.get("completed_at")),
                "duration_ms": t.get("duration_ms"),
                "plan": {
                    "engine": (t.get("plan") or {}).get("engine"),
                    "components": list((t.get("plan") or {}).get("components") or []),
                    "qa_checks": list((t.get("plan") or {}).get("qa_checks") or []),
                },
                "checks": [f"{c.get('evidence_ref')} {c.get('source')} {clean(c.get('title'), 200)}" for c in t.get("checks") or []],
                "source_runs": [
                    f"{r.get('engine')}:{r.get('run_id')} ({r.get('status') or '?'})" for r in t.get("source_runs") or []
                ],
                "matched_evidence_refs": [_ref(ev_by_id, x) for x in t.get("matched_evidence_ids") or []],
                "observations": [
                    f"{o.get('source')} | {o.get('status')} | {clean(o.get('title'), 200)} | {clean(o.get('target_component'), 300)}"
                    for o in t.get("observations") or []
                ],
                "result_summary": clean(summary.get("reason"), 800) if summary else None,
                "results_evaluated": summary.get("results_evaluated") if summary else None,
                "error": f"{clean(err.get('category'), 60)}: {clean(err.get('message'), 500)}" if err else None,
            }
        )

    outcomes = [r["outcome"] for r in retest_rows]
    priority_counts = {p: sum(1 for i in issues if i.get("priority") == p) for p in PRIORITIES}
    summary = {
        "assessment_status": assessment.get("status"),
        "partial": bool(assessment.get("partial")),
        "qa": qa["counts"],
        "security": security["counts"],
        "evidence_total": len(evidence),
        "issue_total": len(issues),
        "priority_counts": priority_counts,
        "ai_analysis_status": ai["status"],
        "correlation_status": correlation["status"],
        "recommendation_status": recs["status"],
        "recommendation_count": len(recs["items"]),
        "retests": {
            "total": len(retest_rows),
            "passed": outcomes.count("PASS"),
            "failed": outcomes.count("FAIL"),
            "execution_failed": outcomes.count("EXECUTION_FAILED"),
            "running": outcomes.count("RUNNING"),
        },
    }

    return {
        "meta": {
            "report_version": REPORT_VERSION,
            "assessment_id": aid,
            "target_id": str(assessment.get("target_id")),
        },
        "summary": summary,
        "target": snapshot,
        "pipeline": pipeline,
        "qa": qa,
        "security": security,
        "evidence": rows,
        "ai": ai,
        "correlation": correlation,
        "recommendations": recs,
        "retests": retest_rows,
        "traceability": traceability,
    }


def retest_outcome(retest: dict[str, Any]) -> str:
    """PASS / FAIL only for a completed retest; an execution failure has no verdict."""
    status = retest.get("status")
    if status == "running":
        return "RUNNING"
    if status == "failed":
        return "EXECUTION_FAILED"
    if status == "completed" and retest.get("verdict") in ("PASS", "FAIL"):
        return str(retest["verdict"])
    return "NO_VERDICT"


def _spec(spec: dict[str, Any], ev_by_id: dict[str, dict]) -> dict[str, Any] | None:
    if not spec:
        return None
    return {
        "retest_type": spec.get("retest_type"),
        "scope": spec.get("scope"),
        "target_component": clean(spec.get("target_component"), 500),
        "pass_condition": spec.get("pass_condition"),
        "match_key": clean(spec.get("match_key"), 500),
        "checks": [f"{c.get('evidence_ref')} {c.get('source')} {clean(c.get('title'), 200)}" for c in spec.get("checks") or []],
        "expected_result": clean(spec.get("expected_result"), 1000),
        "pass_criteria": clean(spec.get("pass_criteria"), 1000),
        "fail_criteria": clean(spec.get("fail_criteria"), 1000),
    }
