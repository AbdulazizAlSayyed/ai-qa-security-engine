"""Build correlation groups from one assessment's evidence.

Pure functions over plain dicts: no database, no network, no model. The
service loads the evidence, calls :func:`correlate`, and persists what comes
back; the same evidence always yields the same groups in the same order.

Only evidence that reports something is correlated - ``failed``, ``error``
and ``observed``. ``passed`` and ``skipped`` records describe no issue; they
are counted in the result and otherwise left alone.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from app.engines.correlation.keys import (
    RULE_DESCRIPTIONS,
    CorrelationKey,
    CorrelationRule,
    correlation_key,
    missing_header,
    normalize_endpoint,
    rule_id_of,
)

#: Evidence statuses that can form an issue.
ACTIONABLE_STATUSES: tuple[str, ...] = ("failed", "error", "observed")

#: Tool severities in the Phase 3 vocabulary, most severe first.
SEVERITY_ORDER: tuple[str, ...] = ("high", "medium", "low", "informational")


class EvidenceOwnershipError(ValueError):
    """Evidence handed to correlation does not belong to the assessment."""


def evidence_ref(sequence: Any) -> str:
    """Same ``EV-###`` reference the AI analysis and the evidence table use."""
    return f"EV-{int(sequence) + 1:03d}"


def highest_severity(values: Iterable[str | None]) -> str | None:
    present = {value for value in values if value in SEVERITY_ORDER}
    for severity in SEVERITY_ORDER:
        if severity in present:
            return severity
    return None


@dataclass
class CorrelatedGroup:
    """Evidence records sharing one correlation key, in evidence order."""

    key: CorrelationKey
    members: list[dict[str, Any]] = field(default_factory=list)

    @property
    def group_key(self) -> str:
        return self.key.group_key

    @property
    def rule(self) -> CorrelationRule:
        return self.key.rule

    @property
    def finding_type(self) -> str:
        return self.key.finding_type

    @property
    def representative(self) -> dict[str, Any]:
        """The earliest record: it gives the group its title."""
        return self.members[0]

    @property
    def first_sequence(self) -> int:
        return int(self.representative.get("sequence", 0))

    @property
    def evidence_ids(self) -> list[str]:
        return [str(member["evidence_id"]) for member in self.members]

    @property
    def evidence_refs(self) -> list[str]:
        return [evidence_ref(member.get("sequence", 0)) for member in self.members]

    @property
    def sources(self) -> list[str]:
        return sorted({str(member.get("source") or "") for member in self.members})

    @property
    def categories(self) -> list[str]:
        return sorted({str(member.get("category") or "") for member in self.members})

    @property
    def statuses(self) -> list[str]:
        return sorted({str(member.get("status") or "") for member in self.members})

    @property
    def affected_components(self) -> list[str]:
        """Distinct components, as the tools reported them, in evidence order."""
        seen: dict[str, None] = {}
        for member in self.members:
            seen.setdefault(str(member.get("target_component") or ""), None)
        return list(seen)

    @property
    def distinct_endpoints(self) -> int:
        """Components counted after normalization (``GET http://x/`` == ``http://x``)."""
        return len(
            {normalize_endpoint(str(m.get("target_component") or "")) for m in self.members}
        )

    @property
    def tool_severity(self) -> str | None:
        """The most severe tool severity any member carries (copied, never assigned)."""
        return highest_severity(member.get("tool_severity") for member in self.members)

    @property
    def rule_ids(self) -> list[str]:
        return sorted({rid for rid in (rule_id_of(m) for m in self.members) if rid})

    def reason(self) -> str:
        """Plain-language explanation of why these records are one group."""
        count = len(self.members)
        records = f"{count} evidence record{'' if count == 1 else 's'}"
        components = len(self.affected_components)
        where = f"{components} component{'' if components == 1 else 's'}"
        sources = ", ".join(self.sources)
        rule = self.rule
        if rule is CorrelationRule.SAME_MISSING_HEADER_AND_ORIGIN:
            header = missing_header(self.representative) or "?"
            return (
                f"{records} from {sources} report the '{header}' response header missing "
                f"on {self.key.scope} ({where})."
            )
        if rule is CorrelationRule.SAME_SCANNER_RULE_AND_ORIGIN:
            rules = ", ".join(self.rule_ids)
            return (
                f"{records} from {sources} share scanner rule {rules} and the alert title "
                f"'{self.representative.get('title')}' on {self.key.scope} ({where})."
            )
        if rule is CorrelationRule.SAME_NORMALIZED_IDENTITY:
            return (
                f"{records} from {sources} share the title "
                f"'{self.representative.get('title')}' on {self.key.scope}."
            )
        return (
            f"{records} of the QA check '{self.representative.get('title')}' "
            f"({self.representative.get('category')}) on {self.key.scope}."
        )

    def rule_description(self) -> str:
        return RULE_DESCRIPTIONS[self.rule]


@dataclass
class CorrelationOutcome:
    groups: list[CorrelatedGroup]
    evidence_total: int
    evidence_considered: int
    #: Records not correlated, by status (``passed``, ``skipped``).
    evidence_excluded: dict[str, int]


def check_ownership(assessment_id: str, evidence: Iterable[Mapping[str, Any]]) -> None:
    """Every record must belong to ``assessment_id``, and ids must be unique."""
    seen: set[str] = set()
    for item in evidence:
        if str(item.get("assessment_id")) != assessment_id:
            raise EvidenceOwnershipError(
                f"Evidence {item.get('evidence_id')} belongs to assessment "
                f"{item.get('assessment_id')}, not {assessment_id}."
            )
        evidence_id = str(item.get("evidence_id") or "")
        if not evidence_id or evidence_id in seen:
            raise EvidenceOwnershipError(
                f"Evidence id {evidence_id!r} is missing or duplicated in assessment {assessment_id}."
            )
        seen.add(evidence_id)


def correlate(assessment_id: str, evidence: Iterable[Mapping[str, Any]]) -> CorrelationOutcome:
    """Group one assessment's evidence. Deterministic for a given evidence set."""
    records = [dict(item) for item in evidence]
    check_ownership(assessment_id, records)
    records.sort(key=lambda item: (int(item.get("sequence", 0)), str(item["evidence_id"])))

    groups: dict[str, CorrelatedGroup] = {}
    excluded: Counter[str] = Counter()
    considered = 0
    for record in records:
        status = str(record.get("status") or "")
        if status not in ACTIONABLE_STATUSES:
            excluded[status or "unknown"] += 1
            continue
        considered += 1
        key = correlation_key(record)
        group = groups.get(key.group_key)
        if group is None:
            group = groups[key.group_key] = CorrelatedGroup(key=key)
        group.members.append(record)

    ordered = sorted(groups.values(), key=lambda g: (g.first_sequence, g.group_key))
    return CorrelationOutcome(
        groups=ordered,
        evidence_total=len(records),
        evidence_considered=considered,
        evidence_excluded=dict(sorted(excluded.items())),
    )


def assign_reference_numbers(ordered_keys: list[str], existing: Mapping[str, int]) -> dict[str, int]:
    """Stable human-readable numbering (``CG-001``, ``ISSUE-001``...).

    A key that already has a number keeps it, so re-processing never renames
    an issue. New keys get the next free numbers, in the given order.
    """
    numbers: dict[str, int] = {}
    next_number = max(existing.values(), default=0) + 1
    for key in ordered_keys:
        if key in existing:
            numbers[key] = int(existing[key])
        else:
            numbers[key] = next_number
            next_number += 1
    return numbers


# --- supporting AI findings -------------------------------------------------------


@dataclass(frozen=True)
class AIFindingLink:
    finding_id: str
    title: str
    status: str
    confidence: str
    #: The group's evidence this AI finding cites.
    evidence_refs: tuple[str, ...]


@dataclass
class AILinkResult:
    links: dict[str, list[AIFindingLink]]
    #: AI citations dropped because the evidence is not in this assessment.
    ignored_references: int


def link_ai_findings(
    groups: list[CorrelatedGroup],
    findings: Iterable[Mapping[str, Any]],
    owned_evidence_ids: set[str],
) -> AILinkResult:
    """Attach completed-analysis AI findings to the groups whose evidence they cite.

    Supporting metadata only: an AI finding never creates, merges or splits a
    group. It is linked when it has the group's finding type and cites at
    least one of the group's evidence records. Citations of evidence outside
    this assessment are ignored and counted.
    """
    links: dict[str, list[AIFindingLink]] = {group.group_key: [] for group in groups}
    index: dict[str, list[CorrelatedGroup]] = {}
    for group in groups:
        for evidence_id in group.evidence_ids:
            index.setdefault(evidence_id, []).append(group)

    ignored = 0
    for finding in findings:
        cited = [str(eid) for eid in finding.get("evidence_ids") or []]
        owned = [eid for eid in cited if eid in owned_evidence_ids]
        ignored += len(cited) - len(owned)
        matched: dict[str, CorrelatedGroup] = {}
        for evidence_id in owned:
            for group in index.get(evidence_id, []):
                if group.finding_type == finding.get("type"):
                    matched[group.group_key] = group
        for group_key, group in matched.items():
            group_ids = set(group.evidence_ids)
            refs = tuple(
                evidence_ref(member.get("sequence", 0))
                for member in group.members
                if member["evidence_id"] in group_ids and member["evidence_id"] in owned
            )
            links[group_key].append(
                AIFindingLink(
                    finding_id=str(finding.get("finding_id")),
                    title=str(finding.get("title") or ""),
                    status=str(finding.get("status") or ""),
                    confidence=str(finding.get("confidence") or ""),
                    evidence_refs=refs,
                )
            )
    for group_links in links.values():
        group_links.sort(key=lambda link: link.finding_id)
    return AILinkResult(links=links, ignored_references=ignored)
