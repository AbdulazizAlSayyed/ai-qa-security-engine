"""Evidence traceability audit (Phase 10).

Walks the chain that every report claims::

    target -> assessment -> raw QA / security run -> evidence
           -> AI analysis -> correlation group -> issue
           -> recommendation -> retest -> report

Optional links may be absent (no AI analysis, no recommendation, no retest
yet) - that is a valid state. But every reference that *is* stored must
resolve, inside the same assessment. Nothing is repaired or invented: the
audit only reports what is broken, by reference (EV-###, ISSUE-###, ...),
never by content, so an error message cannot leak data.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.engines.ai.context import evidence_ref

_QA_FINDING = re.compile(r"^(tests|console_errors|network_failures)\[(\d+)\]$")


@dataclass(frozen=True)
class TraceError:
    relationship: str
    source: str
    reference: str
    problem: str

    def as_dict(self) -> dict[str, str]:
        return {
            "relationship": self.relationship,
            "source": self.source,
            "reference": self.reference,
            "problem": self.problem,
        }


@dataclass
class TraceInputs:
    """Everything the audit needs, already loaded by the service (read-only)."""

    assessment: dict[str, Any]
    target: dict[str, Any] | None
    qa_run: dict[str, Any] | None
    security_run: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    #: evidence_id -> assessment_id, for referenced ids that are not this
    #: assessment's evidence but exist elsewhere (cross-assessment references).
    foreign_evidence: dict[str, str] = field(default_factory=dict)
    analyses: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    retests: list[dict[str, Any]] = field(default_factory=list)
    #: run_id -> target_id for every raw run a retest says it produced.
    retest_runs: dict[str, str | None] = field(default_factory=dict)


@dataclass
class TraceResult:
    errors: list[TraceError]
    checks: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "passed" if self.ok else "failed",
            "checks": dict(sorted(self.checks.items())),
            "links_checked": sum(self.checks.values()),
            "errors": [e.as_dict() for e in self.errors],
        }


def referenced_evidence_ids(inputs: TraceInputs) -> set[str]:
    """Every evidence id any derived record points at (to look up foreign ones)."""
    ids: set[str] = set()
    for analysis in inputs.analyses:
        for finding in ((analysis.get("result") or {}).get("findings") or []):
            ids.update(finding.get("evidence_ids") or [])
    for doc in (*inputs.groups, *inputs.issues, *inputs.recommendations):
        ids.update(doc.get("evidence_ids") or [])
    for rec in inputs.recommendations:
        for check in ((rec.get("retest") or {}).get("checks") or []):
            if check.get("evidence_id"):
                ids.add(check["evidence_id"])
    for retest in inputs.retests:
        ids.update(retest.get("matched_evidence_ids") or [])
        ids.update(c.get("evidence_id") for c in (retest.get("checks") or []) if c.get("evidence_id"))
    return ids


def audit(inputs: TraceInputs) -> TraceResult:
    errors: list[TraceError] = []
    checks: Counter[str] = Counter()
    a = inputs.assessment
    aid = str(a["_id"])
    target_id = str(a.get("target_id") or "")

    def fail(rel: str, source: str, ref: str, problem: str) -> None:
        errors.append(TraceError(rel, source, ref, problem))

    # --- evidence lookup -------------------------------------------------------
    own = {str(e["evidence_id"]): e for e in inputs.evidence}

    def check_evidence(rel: str, source: str, ids: list[str], refs: list[str] | None = None) -> None:
        for index, eid in enumerate(ids or []):
            checks[rel] += 1
            eid = str(eid)
            if eid in own:
                if refs is not None and index < len(refs):
                    expected = evidence_ref(own[eid].get("sequence", 0))
                    if refs[index] != expected:
                        fail(rel, source, refs[index], f"reference does not match its evidence ({expected})")
                continue
            if eid in inputs.foreign_evidence:
                fail(rel, source, eid, "evidence belongs to a different assessment")
            else:
                fail(rel, source, eid, "evidence does not exist")

    # --- assessment -> target ----------------------------------------------------
    checks["assessment->target"] += 1
    snapshot_ok = bool(a.get("target_name")) and bool(a.get("target_base_url"))
    if inputs.target is None:
        if not snapshot_ok:
            fail("assessment->target", "assessment", target_id or "-", "target is not registered and the assessment has no target snapshot")
    elif str(inputs.target.get("_id")) != target_id:
        fail("assessment->target", "assessment", target_id or "-", "target id does not resolve")
    elif not snapshot_ok:
        fail("assessment->target", "assessment", target_id, "assessment has no target snapshot (name / base URL)")

    # --- assessment -> raw runs ---------------------------------------------------
    runs = {"qa": (a.get("qa_run_id"), inputs.qa_run), "security": (a.get("security_run_id"), inputs.security_run)}
    for engine, (run_id, run) in runs.items():
        if not run_id:
            continue
        rel = f"assessment->{engine}_run"
        checks[rel] += 1
        if run is None:
            fail(rel, "assessment", str(run_id), f"{engine} run does not exist")
        elif str(run.get("target_id")) != target_id:
            fail(rel, "assessment", str(run_id), f"{engine} run belongs to a different target")

    # --- evidence -> assessment, source run, source finding ----------------------
    for e in inputs.evidence:
        ref = evidence_ref(e.get("sequence", 0))
        checks["evidence->assessment"] += 1
        if str(e.get("assessment_id")) != aid:
            fail("evidence->assessment", ref, str(e.get("evidence_id")), "evidence belongs to a different assessment")
        engine = e.get("finding_type")
        run_id, run = runs.get(engine, (None, None))
        checks["evidence->source_run"] += 1
        if not e.get("source_run_id"):
            fail("evidence->source_run", ref, "-", "evidence has no source run")
            continue
        if str(e.get("source_run_id")) != str(run_id or ""):
            fail("evidence->source_run", ref, str(e.get("source_run_id")), f"source run is not this assessment's {engine} run")
            continue
        if run is None:
            continue  # already reported against the assessment
        checks["evidence->source_finding"] += 1
        if not _finding_resolves(engine, str(e.get("source_finding_id") or ""), run):
            fail("evidence->source_finding", ref, str(e.get("source_finding_id") or "-"), "source finding does not exist in the source run")

    # --- AI analyses -> evidence -------------------------------------------------
    analyses = {str(x.get("analysis_id")): x for x in inputs.analyses}
    for analysis in inputs.analyses:
        label = f"analysis {str(analysis.get('analysis_id'))[:8]}"
        checks["ai_analysis->assessment"] += 1
        if str(analysis.get("assessment_id")) != aid:
            fail("ai_analysis->assessment", label, str(analysis.get("analysis_id")), "analysis belongs to a different assessment")
        for finding in ((analysis.get("result") or {}).get("findings") or []):
            check_evidence("ai_finding->evidence", f"{label} {finding.get('finding_id')}",
                           finding.get("evidence_ids") or [], finding.get("evidence_refs"))

    def analysis_ok(rel: str, source: str, analysis_id: str | None, *, completed: bool = True) -> dict | None:
        checks[rel] += 1
        found = analyses.get(str(analysis_id))
        if found is None:
            fail(rel, source, str(analysis_id), "AI analysis is not an analysis of this assessment")
            return None
        if completed and found.get("status") != "completed":
            fail(rel, source, str(analysis_id), "AI analysis did not complete")
        return found

    # --- correlation groups -> evidence ------------------------------------------
    groups = {str(g.get("correlation_group_id")): g for g in inputs.groups}
    for g in inputs.groups:
        check_evidence("correlation_group->evidence", str(g.get("correlation_group_id")), g.get("evidence_ids") or [], g.get("evidence_refs"))

    # --- issues -> group, evidence, AI findings ------------------------------------
    issues = {str(i.get("issue_id")): i for i in inputs.issues}
    for issue in inputs.issues:
        iid = str(issue.get("issue_id"))
        checks["issue->correlation_group"] += 1
        group = groups.get(str(issue.get("correlation_group_id")))
        if group is None:
            fail("issue->correlation_group", iid, str(issue.get("correlation_group_id")), "correlation group does not exist in this assessment")
        elif group.get("group_key") != issue.get("group_key"):
            fail("issue->correlation_group", iid, str(issue.get("correlation_group_id")), "group key does not match the issue")
        check_evidence("issue->evidence", iid, issue.get("evidence_ids") or [], issue.get("evidence_refs"))
        if group is not None:
            outside = sorted(set(issue.get("evidence_ids") or []) - set(group.get("evidence_ids") or []))
            for eid in outside:
                fail("issue->evidence", iid, eid, "evidence is not part of the issue's correlation group")
        if issue.get("ai_analysis_id") or issue.get("ai_finding_ids"):
            found = analysis_ok("issue->ai_analysis", iid, issue.get("ai_analysis_id"))
            if found is not None:
                known = {f.get("finding_id") for f in ((found.get("result") or {}).get("findings") or [])}
                for fid in issue.get("ai_finding_ids") or []:
                    checks["issue->ai_finding"] += 1
                    if fid not in known:
                        fail("issue->ai_finding", iid, str(fid), "AI finding does not exist in the analysis")

    # --- recommendations -> issue, analysis, evidence, retest spec ----------------
    recs_by_ref = {str(r.get("_id")): r for r in inputs.recommendations}
    for rec in inputs.recommendations:
        rid = str(rec.get("recommendation_id"))
        checks["recommendation->assessment"] += 1
        if str(rec.get("assessment_id")) != aid:
            fail("recommendation->assessment", rid, rid, "recommendation belongs to a different assessment")
        for issue_id in [rec.get("issue_id"), *(rec.get("related_issue_ids") or [])]:
            checks["recommendation->issue"] += 1
            if str(issue_id) not in issues:
                fail("recommendation->issue", rid, str(issue_id), "issue does not exist in this assessment")
        analysis_ok("recommendation->ai_analysis", rid, rec.get("ai_analysis_id"))
        check_evidence("recommendation->evidence", rid, rec.get("evidence_ids") or [], rec.get("evidence_refs"))
        spec = rec.get("retest") or {}
        if spec:
            issue = issues.get(str(spec.get("issue_id")))
            checks["recommendation->retest_spec"] += 1
            if issue is None or issue.get("group_key") != spec.get("match_key"):
                fail("recommendation->retest_spec", rid, str(spec.get("issue_id")), "retest specification does not match its issue")
            check_evidence("recommendation->retest_spec", rid,
                           [c.get("evidence_id") for c in spec.get("checks") or []],
                           [c.get("evidence_ref") for c in spec.get("checks") or []])

    # --- retests -> recommendation, issue, evidence, source runs -----------------
    for retest in inputs.retests:
        tid = str(retest.get("retest_id"))
        checks["retest->recommendation"] += 1
        rec = recs_by_ref.get(str(retest.get("recommendation_ref")))
        if rec is None:
            fail("retest->recommendation", tid, str(retest.get("recommendation_id")), "recommendation does not exist in this assessment")
        elif rec.get("recommendation_id") != retest.get("recommendation_id"):
            fail("retest->recommendation", tid, str(retest.get("recommendation_id")), "recommendation reference does not match")
        checks["retest->issue"] += 1
        issue = issues.get(str(retest.get("issue_id")))
        if issue is None:
            fail("retest->issue", tid, str(retest.get("issue_id")), "issue does not exist in this assessment")
        elif issue.get("group_key") != retest.get("match_key"):
            fail("retest->issue", tid, str(retest.get("issue_id")), "match key does not match the issue")
        check_evidence("retest->original_evidence", tid, retest.get("matched_evidence_ids") or [], retest.get("matched_evidence_refs"))
        check_evidence("retest->original_evidence", tid, [c.get("evidence_id") for c in retest.get("checks") or []],
                       [c.get("evidence_ref") for c in retest.get("checks") or []])
        for run_id in retest.get("source_run_ids") or []:
            checks["retest->source_run"] += 1
            if str(run_id) not in inputs.retest_runs:
                fail("retest->source_run", tid, str(run_id), "raw run does not exist")
            elif str(inputs.retest_runs[str(run_id)]) != target_id:
                fail("retest->source_run", tid, str(run_id), "raw run belongs to a different target")

    return TraceResult(errors=errors, checks=dict(checks))


def _finding_resolves(engine: str | None, finding_id: str, run: dict[str, Any]) -> bool:
    if engine == "qa":
        match = _QA_FINDING.match(finding_id)
        return bool(match) and int(match.group(2)) < len(run.get(match.group(1)) or [])
    findings = list(run.get("findings") or [])
    for component in run.get("components") or []:
        findings.extend(component.get("findings") or [])
    return any(str(f.get("id")) == finding_id for f in findings)
