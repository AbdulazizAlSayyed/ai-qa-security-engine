"""Deterministic validation of model output.

The model is never trusted because it returned JSON. An answer is accepted
only when every check below passes; otherwise the whole analysis is
rejected - nothing is repaired, dropped or "fixed up":

1. It parses as a single JSON object.
2. It matches :class:`AIAnalysisOutput` exactly (required fields, allowed
   enum values, no extra keys - so an invented ``severity`` or
   ``risk_score`` fails).
3. Finding ids are unique.
4. Every cited reference was supplied in this assessment's context. An
   unknown reference is a hallucination and fails the analysis.
5. A finding's ``type`` matches at least one cited record's type.
6. A non-null ``tool_severity`` is one the cited evidence actually carries;
   the model cannot raise, lower or invent severity.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.engines.ai.context import EvidenceContext
from app.engines.ai.models import AIAnalysisOutput, AIAnalysisResult, AIFinding


class AnalysisValidationError(Exception):
    """The model's answer was rejected. ``code`` is machine-readable."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*)\n\s*```\s*$", re.DOTALL | re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the answer. A single fenced ```json block is unwrapped; nothing else is."""
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        data = json.loads(candidate)
    except ValueError as exc:  # JSONDecodeError is a ValueError
        where = f" ({exc.msg} at char {exc.pos})" if isinstance(exc, json.JSONDecodeError) else ""
        raise AnalysisValidationError(
            "invalid_json", f"The model's answer is not valid JSON{where}."
        ) from exc
    if not isinstance(data, dict):
        raise AnalysisValidationError(
            "invalid_json", "The model's answer is JSON but not a single object."
        )
    return data


def _schema_problems(exc: ValidationError) -> list[str]:
    """Field paths and messages only - never the offending values."""
    problems = []
    for error in exc.errors()[:20]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        problems.append(f"{location or '(root)'}: {error.get('msg', 'invalid')}")
    return problems


def validate_analysis(text: str, context: EvidenceContext) -> AIAnalysisResult:
    """Validate the model's answer against the schema and the supplied evidence."""
    data = parse_json_object(text)

    try:
        output = AIAnalysisOutput.model_validate(data)
    except ValidationError as exc:
        problems = _schema_problems(exc)
        raise AnalysisValidationError(
            "schema_violation",
            f"The model's answer does not match the analysis schema ({len(problems)} problem"
            f"{'' if len(problems) == 1 else 's'}): {'; '.join(problems[:5])}",
            {"problems": problems},
        ) from exc

    seen: set[str] = set()
    duplicates = [f.finding_id for f in output.findings if f.finding_id in seen or seen.add(f.finding_id)]
    if duplicates:
        raise AnalysisValidationError(
            "duplicate_finding_id",
            f"Finding ids must be unique; repeated: {', '.join(sorted(set(duplicates)))}.",
            {"finding_ids": sorted(set(duplicates))},
        )

    findings: list[AIFinding] = []
    for finding in output.findings:
        refs = list(dict.fromkeys(finding.evidence_ids))  # order-preserving de-dupe

        unknown = [ref for ref in refs if ref not in context.refs]
        if unknown:
            raise AnalysisValidationError(
                "unknown_evidence_reference",
                f"{finding.finding_id} cites evidence that was not supplied for this "
                f"assessment: {', '.join(unknown[:10])}.",
                {"finding_id": finding.finding_id, "unknown": unknown},
            )

        cited = [context.refs[ref] for ref in refs]

        cited_types = {item.finding_type for item in cited}
        if finding.type not in cited_types:
            raise AnalysisValidationError(
                "finding_type_mismatch",
                f"{finding.finding_id} is typed {finding.type!r} but cites only "
                f"{'/'.join(sorted(cited_types))} evidence.",
                {"finding_id": finding.finding_id},
            )

        cited_severities = {item.tool_severity for item in cited if item.tool_severity}
        if finding.tool_severity is not None and finding.tool_severity not in cited_severities:
            raise AnalysisValidationError(
                "unsupported_severity",
                f"{finding.finding_id} states tool_severity {finding.tool_severity!r}, which "
                f"none of its cited evidence carries "
                f"({', '.join(sorted(cited_severities)) or 'no severity'}).",
                {"finding_id": finding.finding_id},
            )

        findings.append(
            AIFinding(
                finding_id=finding.finding_id,
                type=finding.type,
                status=finding.status,
                title=finding.title,
                description=finding.description,
                impact=finding.impact,
                confidence=finding.confidence,
                tool_severity=finding.tool_severity,
                evidence_ids=[item.evidence_id for item in cited],
                evidence_refs=refs,
                # From the evidence, never from the model.
                affected_components=list(
                    dict.fromkeys(item.target_component for item in cited if item.target_component)
                ),
                uncertainty=finding.uncertainty,
            )
        )

    return AIAnalysisResult(
        overall_assessment=output.overall_assessment,
        findings=findings,
        evidence_gaps=output.evidence_gaps,
        limitations=output.limitations,
    )
