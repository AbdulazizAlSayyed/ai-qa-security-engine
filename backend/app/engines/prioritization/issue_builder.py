"""Turn correlation groups into stored group and issue fields.

Pure assembly: every value comes from the group's evidence, its linked AI
findings, and :mod:`app.engines.prioritization.scoring`. Titles and
descriptions are written from structured fields; no model text is copied
into an issue's own title or description, and no severity is assigned.
Timestamps and database ids are added by the service.
"""

from __future__ import annotations

from typing import Any

from app.engines.correlation.correlator import AIFindingLink, CorrelatedGroup
from app.engines.correlation.keys import CORRELATION_VERSION, CorrelationRule, missing_header
from app.engines.prioritization.scoring import (
    PRIORITY_MODEL_VERSION,
    AISupport,
    PriorityInputs,
    PriorityResult,
    compute_priority,
)


def group_reference(number: int) -> str:
    return f"CG-{number:03d}"


def issue_reference(number: int) -> str:
    return f"ISSUE-{number:03d}"


def priority_inputs(group: CorrelatedGroup, links: list[AIFindingLink]) -> PriorityInputs:
    return PriorityInputs(
        finding_type=group.finding_type,
        tool_severity=group.tool_severity,
        statuses=tuple(group.statuses),
        sources=tuple(group.sources),
        evidence_count=len(group.members),
        distinct_endpoints=group.distinct_endpoints,
        ai_support=tuple(
            AISupport(finding_id=link.finding_id, status=link.status, confidence=link.confidence)
            for link in links
        ),
    )


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def describe(group: CorrelatedGroup) -> str:
    """A factual description built from the evidence fields."""
    first = group.representative
    records = _plural(len(group.members), "evidence record")
    components = _plural(len(group.affected_components), "component")
    sources = " and ".join(group.sources)
    if group.rule is CorrelationRule.SAME_MISSING_HEADER_AND_ORIGIN:
        header = missing_header(first)
        return (
            f"{sources} reported that responses from {group.key.scope} do not include the "
            f"'{header}' header ({records}, {components})."
        )
    if group.finding_type == "security":
        severity = group.tool_severity or "no"
        return (
            f"{sources} reported '{first.get('title')}' with {severity} tool severity on "
            f"{group.key.scope} ({records}, {components})."
        )
    statuses = set(group.statuses)
    if "failed" in statuses:
        verb = "failed"
    elif "error" in statuses:
        verb = "could not complete"
    else:
        verb = "recorded an observation"
    detail = f" Observed: {first.get('actual')}" if first.get("actual") else ""
    return (
        f"The QA check '{first.get('title')}' ({first.get('category')}) {verb} on "
        f"{group.key.scope} ({records}).{detail}"
    )


def build_group_fields(assessment_id: str, group: CorrelatedGroup, number: int) -> dict[str, Any]:
    first = group.representative
    return {
        "correlation_group_id": group_reference(number),
        "group_number": number,
        "assessment_id": assessment_id,
        "group_key": group.group_key,
        "correlation_rule": group.rule.value,
        "correlation_rule_description": group.rule_description(),
        "correlation_reason": group.reason(),
        "correlation_version": CORRELATION_VERSION,
        "finding_type": group.finding_type,
        "identity": group.key.identity,
        "target_component": group.key.scope,
        "affected_components": group.affected_components,
        "categories": group.categories,
        "sources": group.sources,
        "evidence_statuses": group.statuses,
        "tool_severity": group.tool_severity,
        "representative_title": str(first.get("title") or ""),
        "representative_evidence_id": str(first["evidence_id"]),
        "evidence_ids": group.evidence_ids,
        "evidence_refs": group.evidence_refs,
        "evidence_count": len(group.members),
    }


def build_issue_fields(
    assessment_id: str,
    group: CorrelatedGroup,
    group_number: int,
    issue_number: int,
    links: list[AIFindingLink],
    ai_analysis_id: str | None,
) -> tuple[dict[str, Any], PriorityResult]:
    priority = compute_priority(priority_inputs(group, links))
    fields = {
        "issue_id": issue_reference(issue_number),
        "issue_number": issue_number,
        "assessment_id": assessment_id,
        "correlation_group_id": group_reference(group_number),
        "group_key": group.group_key,
        "type": group.finding_type,
        "title": str(group.representative.get("title") or ""),
        "description": describe(group),
        "priority": priority.priority,
        "priority_score": priority.priority_score,
        "priority_reasons": list(priority.reasons),
        "score_factors": [
            {"factor": f.factor, "points": f.points, "detail": f.detail} for f in priority.factors
        ],
        "priority_model_version": PRIORITY_MODEL_VERSION,
        # Copied from the evidence; never derived from the priority.
        "tool_severity": group.tool_severity,
        # The AI's confidence in its own interpretation, only when counted.
        "confidence": priority.ai_confidence,
        "affected_components": group.affected_components,
        "sources": group.sources,
        "correlation_rule": group.rule.value,
        "evidence_ids": group.evidence_ids,
        "evidence_refs": group.evidence_refs,
        "evidence_count": len(group.members),
        "ai_analysis_id": ai_analysis_id if links else None,
        "ai_finding_ids": [link.finding_id for link in links],
        "ai_findings": [
            {
                "finding_id": link.finding_id,
                "title": link.title,
                "status": link.status,
                "confidence": link.confidence,
                "evidence_refs": list(link.evidence_refs),
            }
            for link in links
        ],
    }
    return fields, priority
