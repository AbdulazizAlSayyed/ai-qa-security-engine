"""Deterministic validation of a recommendation answer.

The answer is accepted only when every check passes; otherwise the whole
generation is rejected. Nothing is repaired, dropped or re-mapped:

1. ``invalid_json``            - one JSON object (Phase 5 parser).
2. ``schema_violation``        - matches :class:`RecommendationsOutput` exactly
                                 (enums, required fields, no extra keys).
3. ``unknown_issue_reference`` - every primary/related issue was supplied.
4. ``duplicate_recommendation``- at most one recommendation per primary issue.
5. ``unknown_evidence_reference`` - every EV-### was supplied.
6. ``evidence_not_linked``     - cited evidence belongs to the cited issues.
7. ``invalid_retest_specification`` - the retest component is one of the
   primary issue's components (or its scope) and the retest evidence is the
   primary issue's own evidence.

The structural retest fields are then *derived* from stored records, never
taken from the model.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.engines.ai.validation import AnalysisValidationError, parse_json_object
from app.engines.remediation.context import IssueRef, RecommendationContext
from app.engines.remediation.models import (
    ADVISORY,
    RECOMMENDATION_VERSION,
    Recommendation,
    RecommendationOutput,
    RecommendationsOutput,
    RetestCheck,
    RetestSpecification,
)

#: Phase 6 rules that group per origin (the issue is a property of the server).
ORIGIN_RULES = frozenset({"same_missing_header_and_origin", "same_scanner_rule_and_origin"})

#: Same error type and shape as Phase 5, so failures are reported identically.
RecommendationValidationError = AnalysisValidationError


def recommendation_reference(issue_number: int) -> str:
    """REC-### mirrors the issue number, so the reference is stable across runs."""
    return f"REC-{issue_number:03d}"


def _schema_problems(exc: ValidationError) -> list[str]:
    problems = []
    for error in exc.errors()[:20]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        problems.append(f"{location or '(root)'}: {error.get('msg', 'invalid')}")
    return problems


def _fail(code: str, message: str, **details: Any) -> AnalysisValidationError:
    return AnalysisValidationError(code, message, details)


def _retest(
    context: RecommendationContext, primary: IssueRef, item: RecommendationOutput
) -> RetestSpecification:
    spec = item.retest
    allowed_components = {c.strip() for c in primary.affected_components} | ({primary.scope} if primary.scope else set())
    if spec.target_component.strip() not in allowed_components:
        raise _fail(
            "invalid_retest_specification",
            f"Recommendation for {primary.issue_id}: retest target_component is not one of the "
            "issue's affected components or its scope.",
            issue_id=primary.issue_id,
        )
    retest_refs = list(dict.fromkeys(spec.evidence_ids))
    unknown = [r for r in retest_refs if r not in context.evidence.refs]
    if unknown:
        raise _fail(
            "unknown_evidence_reference",
            f"Retest for {primary.issue_id} cites evidence that was not supplied: {', '.join(unknown[:10])}.",
            issue_id=primary.issue_id,
            unknown=unknown,
        )
    outside = [r for r in retest_refs if r not in primary.evidence_refs]
    if outside:
        raise _fail(
            "invalid_retest_specification",
            f"Retest for {primary.issue_id} must re-verify the issue's own evidence; "
            f"{', '.join(outside[:10])} belongs elsewhere.",
            issue_id=primary.issue_id,
        )

    checks: list[RetestCheck] = []
    for ref in retest_refs:
        evidence_id = context.evidence.refs[ref].evidence_id
        doc = context.evidence_docs[evidence_id]
        payload = doc.get("evidence_payload") or {}
        checks.append(
            RetestCheck(
                evidence_id=evidence_id,
                evidence_ref=ref,
                source=str(doc.get("source") or ""),
                finding_type=doc.get("finding_type"),
                rule_id=str(payload["rule_id"]) if payload.get("rule_id") else None,
                title=str(doc.get("title") or ""),
                target_component=str(doc.get("target_component") or ""),
                baseline_status=str(doc.get("status") or ""),
            )
        )

    target_component = spec.target_component.strip()
    scope = (
        "origin"
        if primary.correlation_rule in ORIGIN_RULES and target_component == primary.scope
        else "component"
    )
    if primary.type == "security":
        retest_type, pass_condition = "security_rescan", "finding_absent"
    else:
        retest_type = "qa_recheck"
        # A failing / erroring check must now pass; an observation must disappear.
        failing = any(check.baseline_status in ("failed", "error") for check in checks)
        pass_condition = "check_passes" if failing else "finding_absent"

    return RetestSpecification(
        retest_type=retest_type,
        scope=scope,
        target_id=context.target_id,
        target_component=target_component,
        issue_id=primary.issue_id,
        match_key=primary.group_key,
        correlation_rule=primary.correlation_rule,
        pass_condition=pass_condition,
        checks=checks,
        preconditions=list(spec.preconditions),
        expected_result=spec.expected_result,
        pass_criteria=spec.pass_criteria,
        fail_criteria=spec.fail_criteria,
    )


def validate_recommendations(
    text: str,
    context: RecommendationContext,
    *,
    ai_analysis_id: str,
    generation_id: str,
    correlation_completed_at: Any = None,
) -> list[Recommendation]:
    """Validate the model's answer against the schema and the supplied records."""
    data = parse_json_object(text)
    try:
        output = RecommendationsOutput.model_validate(data)
    except ValidationError as exc:
        problems = _schema_problems(exc)
        raise _fail(
            "schema_violation",
            f"The answer does not match the recommendation schema ({len(problems)} problem"
            f"{'' if len(problems) == 1 else 's'}): {'; '.join(problems[:5])}",
            problems=problems,
        ) from exc

    seen: set[str] = set()
    records: list[Recommendation] = []
    for item in output.recommendations:
        cited_issues = [item.issue_id, *item.related_issue_ids]
        unknown_issues = [i for i in cited_issues if i not in context.issues]
        if unknown_issues:
            raise _fail(
                "unknown_issue_reference",
                f"A recommendation references issues that were not supplied: {', '.join(unknown_issues[:10])}.",
                unknown=unknown_issues,
            )
        if item.issue_id in seen:
            raise _fail(
                "duplicate_recommendation",
                f"More than one recommendation for {item.issue_id}.",
                issue_id=item.issue_id,
            )
        seen.add(item.issue_id)

        primary = context.issues[item.issue_id]
        related = [i for i in dict.fromkeys(item.related_issue_ids) if i != item.issue_id]

        refs = list(dict.fromkeys(item.evidence_ids))
        unknown = [r for r in refs if r not in context.evidence.refs]
        if unknown:
            raise _fail(
                "unknown_evidence_reference",
                f"Recommendation for {item.issue_id} cites evidence that was not supplied: "
                f"{', '.join(unknown[:10])}.",
                issue_id=item.issue_id,
                unknown=unknown,
            )
        linked = {r for i in [item.issue_id, *related] for r in context.issues[i].evidence_refs}
        unlinked = [r for r in refs if r not in linked]
        if unlinked:
            raise _fail(
                "evidence_not_linked",
                f"Recommendation for {item.issue_id} cites evidence of none of its issues: "
                f"{', '.join(unlinked[:10])}.",
                issue_id=item.issue_id,
            )

        records.append(
            Recommendation(
                recommendation_id=recommendation_reference(primary.issue_number),
                recommendation_number=primary.issue_number,
                assessment_id=context.assessment_id,
                target_id=context.target_id,
                ai_analysis_id=ai_analysis_id,
                generation_id=generation_id,
                correlation_completed_at=correlation_completed_at,
                issue_id=primary.issue_id,
                related_issue_ids=related,
                issue_ids=[primary.issue_id, *related],
                issue_type=primary.type,
                issue_priority=primary.priority,
                type=item.type,
                title=item.title,
                description=item.description,
                rationale=item.rationale,
                confidence=item.confidence,
                advisory_status=ADVISORY,
                # From the issue, never from the model.
                affected_components=list(primary.affected_components),
                evidence_ids=[context.evidence.refs[r].evidence_id for r in refs],
                evidence_refs=refs,
                ai_finding_ids=list(primary.ai_finding_ids),
                retest=_retest(context, primary, item),
                recommendation_version=RECOMMENDATION_VERSION,
            )
        )
    return records
