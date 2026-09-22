"""The data a recommendation prompt is built from - all loaded server-side.

Sources, and only these:

* the prioritized ``issues`` of the assessment (Phase 6), most important
  first, capped at ``max_issues``;
* the ``evidence`` those issues reference, compacted, redacted and budgeted
  by the existing Phase 5 :func:`build_evidence_context` (same ``EV-###``
  references, same secret filter, same delimiter neutralisation);
* the findings of the latest *completed* AI analysis (Phase 5), as
  supporting interpretation;
* the correlation-group scope of each issue (Phase 6).

Every free-text value goes through the Phase 5 ``sanitize_text`` plus a
neutraliser for the extra blocks this prompt uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.engines.ai.context import EvidenceContext, build_evidence_context, evidence_ref, sanitize_text

#: The issue and AI-finding blocks this prompt adds on top of Phase 5's.
_EXTRA_DELIMITER = re.compile(r"(?i)(BEGIN|END)\s+ASSESSMENT\s+(ISSUES|AI\s+FINDINGS)")

_TEXT_LIMITS = {"title": 200, "description": 1500, "impact": 800, "uncertainty": 800, "component": 300}


@dataclass
class IssueRef:
    """What validation and derivation need to know about one supplied issue."""

    issue_id: str
    issue_number: int
    type: str
    priority: str
    group_key: str
    correlation_rule: str
    #: The correlation group's scope (an origin, endpoint or location).
    scope: str
    affected_components: list[str]
    evidence_ids: list[str]
    evidence_refs: list[str]
    ai_finding_ids: list[str]


@dataclass
class RecommendationContext:
    assessment_id: str
    target_id: str
    evidence: EvidenceContext
    issues: dict[str, IssueRef]
    issue_items: list[dict[str, Any]]
    ai_items: list[dict[str, Any]]
    #: Stored evidence documents by evidence_id, for deriving retest checks.
    evidence_docs: dict[str, dict[str, Any]]
    omitted_issues: list[str] = field(default_factory=list)
    redactions: int = 0

    def metadata(self) -> dict[str, Any]:
        return {
            "issues_supplied": len(self.issues),
            "issues_omitted": list(self.omitted_issues),
            "evidence_supplied": len(self.evidence.refs),
            "evidence_omitted": len(self.evidence.omitted),
            "redactions": self.redactions + self.evidence.redactions,
        }


def _clean(value: Any, limit: int, counters: dict[str, int]) -> str:
    text, redacted = sanitize_text(str(value or ""))
    text, neutralised = _EXTRA_DELIMITER.subn("[delimiter removed]", text)
    counters["redactions"] += redacted + neutralised
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def build_recommendation_context(
    *,
    assessment: dict[str, Any],
    issues: list[dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
    analysis_result: dict[str, Any] | None,
    max_issues: int,
    max_items: int,
    max_chars: int,
) -> RecommendationContext:
    """Deterministic for a given input. ``issues`` must already be in priority order."""
    assessment_id = str(assessment.get("id") or assessment.get("_id") or "")
    counters = {"redactions": 0}
    kept_issues = issues[:max_issues]
    omitted = [str(issue.get("issue_id")) for issue in issues[max_issues:]]

    wanted = {eid for issue in kept_issues for eid in issue.get("evidence_ids") or []}
    subset = [doc for doc in evidence if doc.get("evidence_id") in wanted]
    evidence_context = build_evidence_context(assessment, subset, max_items=max_items, max_chars=max_chars)
    by_id = {str(doc["evidence_id"]): doc for doc in subset}

    refs: dict[str, IssueRef] = {}
    items: list[dict[str, Any]] = []
    for issue in kept_issues:
        group = groups.get(str(issue.get("group_key")), {})
        evidence_ids = [str(eid) for eid in issue.get("evidence_ids") or [] if eid in by_id]
        issue_refs = [evidence_ref(by_id[eid].get("sequence", 0)) for eid in evidence_ids]
        ref = IssueRef(
            issue_id=str(issue["issue_id"]),
            issue_number=int(issue["issue_number"]),
            type=str(issue.get("type")),
            priority=str(issue.get("priority")),
            group_key=str(issue.get("group_key")),
            correlation_rule=str(issue.get("correlation_rule")),
            scope=str(group.get("target_component") or ""),
            affected_components=[str(c) for c in issue.get("affected_components") or []],
            evidence_ids=evidence_ids,
            evidence_refs=issue_refs,
            ai_finding_ids=[str(f) for f in issue.get("ai_finding_ids") or []],
        )
        refs[ref.issue_id] = ref
        items.append(
            {
                "issue_id": ref.issue_id,
                "type": ref.type,
                "title": _clean(issue.get("title"), _TEXT_LIMITS["title"], counters),
                "priority": ref.priority,
                "tool_severity": issue.get("tool_severity"),
                "scope": _clean(ref.scope, _TEXT_LIMITS["component"], counters),
                "affected_components": [
                    _clean(c, _TEXT_LIMITS["component"], counters) for c in ref.affected_components[:20]
                ],
                "evidence_ids": [r for r in issue_refs if r in evidence_context.refs],
                "supporting_ai_findings": ref.ai_finding_ids,
            }
        )

    ai_items: list[dict[str, Any]] = []
    for finding in (analysis_result or {}).get("findings") or []:
        ai_items.append(
            {
                "finding_id": str(finding.get("finding_id")),
                "type": finding.get("type"),
                "status": finding.get("status"),
                "confidence": finding.get("confidence"),
                "title": _clean(finding.get("title"), _TEXT_LIMITS["title"], counters),
                "description": _clean(finding.get("description"), _TEXT_LIMITS["description"], counters),
                "impact": _clean(finding.get("impact"), _TEXT_LIMITS["impact"], counters),
                "uncertainty": _clean(finding.get("uncertainty"), _TEXT_LIMITS["uncertainty"], counters),
                "evidence_ids": [
                    r for r in finding.get("evidence_refs") or [] if r in evidence_context.refs
                ],
            }
        )

    return RecommendationContext(
        assessment_id=assessment_id,
        target_id=str(assessment.get("target_id") or ""),
        evidence=evidence_context,
        issues=refs,
        issue_items=items,
        ai_items=ai_items,
        evidence_docs=by_id,
        omitted_issues=omitted,
        redactions=counters["redactions"],
    )
