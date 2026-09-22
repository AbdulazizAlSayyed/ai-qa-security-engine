"""The compact, deterministic context handed to the model.

Built only from the assessment and its normalized evidence - the Phase 4
boundary. Raw runs, scanner payloads, database ids, connection strings and
configuration never enter it.

Each evidence record gets a short reference (``EV-001``) derived from its
normalized ``sequence``. The model cites references, and the platform maps
them back to real ``evidence_id`` values after validation. Short references
are far harder for a model to mistype than 32-character hex ids, and they
are scoped to one assessment, so they cannot reach another assessment's
evidence.

Evidence text is untrusted - it can contain whatever the tested application
or an attacker put in a response - so every string is passed through a
lightweight secret filter and through delimiter neutralisation before it is
serialised as JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

#: Per-field caps. A capped value is marked, never silently shortened.
FIELD_LIMITS: dict[str, int] = {
    "title": 200,
    "category": 60,
    "target_component": 300,
    "expected": 300,
    "actual": 600,
}

#: When the context is over budget, the least informative records go first:
#: passed checks, then skipped, then observations. Failures are kept longest.
_OMIT_ORDER = {"passed": 0, "skipped": 1, "observed": 2, "error": 3, "failed": 4}

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Whole Authorization / Cookie header values.
    (re.compile(r"(?i)\b((?:proxy-)?authorization)\s*[:=]\s*[^\r\n\"',;]+"), r"\1: [REDACTED]"),
    (re.compile(r"(?i)\b(set-cookie|cookie)\s*[:=]\s*[^\r\n\"]+"), r"\1: [REDACTED]"),
    # Bare bearer / basic credentials.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]{8,}=*"), r"\1 [REDACTED]"),
    # key=value / "key": "value" for obviously secret names.
    (
        re.compile(
            r"(?i)([\"']?\b(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|apikey|"
            r"access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?id|token)\b[\"']?"
            r"\s*[:=]\s*[\"']?)[^\"'\s,&;}]+"
        ),
        r"\1[REDACTED]",
    ),
    # Provider-style keys and JWTs anywhere in the text.
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"), "[REDACTED]"),
    # Credentials embedded in connection strings / URLs.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1[REDACTED]@"),
]

#: Evidence may try to fake the end of the data block.
_DELIMITER = re.compile(r"(?i)(BEGIN|END)\s+ASSESSMENT\s+(EVIDENCE|CONTEXT)")


def evidence_ref(sequence: int) -> str:
    """The short reference the model sees. Same rule as the frontend."""
    return f"EV-{int(sequence) + 1:03d}"


def sanitize_text(value: str) -> tuple[str, int]:
    """Redact obvious secrets and neutralise prompt delimiters.

    Returns the cleaned text and how many substitutions were made.
    Deliberately simple: this is a guard against accidents, not a DLP engine.
    """
    count = 0
    for pattern, replacement in _SECRET_PATTERNS:
        value, n = pattern.subn(replacement, value)
        count += n
    value, n = _DELIMITER.subn("[delimiter removed]", value)
    return value, count + n


@dataclass
class EvidenceRef:
    """What validation needs to know about a record the model may cite."""

    ref: str
    evidence_id: str
    finding_type: str
    tool_severity: str | None
    target_component: str


@dataclass
class EvidenceContext:
    assessment: dict[str, Any]
    items: list[dict[str, Any]]
    refs: dict[str, EvidenceRef]
    omitted: list[dict[str, Any]] = field(default_factory=list)
    total_evidence: int = 0
    truncated_fields: int = 0
    redactions: int = 0

    @property
    def supplied_evidence_ids(self) -> list[str]:
        return [ref.evidence_id for ref in self.refs.values()]

    def metadata(self) -> dict[str, Any]:
        """What gets stored on the analysis about the context it was given."""
        return {
            "total_evidence": self.total_evidence,
            "supplied_evidence": len(self.refs),
            "omitted": self.omitted,
            "truncated_fields": self.truncated_fields,
            "redactions": self.redactions,
        }


def _clean(value: Any, limit: int | None, counters: dict[str, int]) -> Any:
    if value is None:
        return None
    text = str(value)
    text, redacted = sanitize_text(text)
    counters["redactions"] += redacted
    if limit is not None and len(text) > limit:
        counters["truncated"] += 1
        text = text[:limit] + " …[truncated]"
    return text


def _compact_assessment(assessment: dict[str, Any], counters: dict[str, int]) -> dict[str, Any]:
    summary = assessment.get("summary") or {}
    return {
        "assessment_id": str(assessment.get("id") or assessment.get("_id") or ""),
        "target_name": _clean(assessment.get("target_name"), 200, counters),
        "target_type": assessment.get("target_type"),
        "target_base_url": _clean(assessment.get("target_base_url"), 300, counters),
        "assessment_status": assessment.get("status"),
        "partial_execution": bool(assessment.get("partial", False)),
        "qa_stage": assessment.get("qa_status"),
        "security_stage": assessment.get("security_status"),
        "qa_summary": summary.get("qa", {}),
        "security_summary": summary.get("security", {}),
        "security_coverage": [
            {"source": item.get("source"), "status": item.get("status")}
            for item in assessment.get("security_coverage") or []
        ],
    }


def _compact_evidence(doc: dict[str, Any], counters: dict[str, int]) -> dict[str, Any]:
    payload = doc.get("evidence_payload") or {}
    item: dict[str, Any] = {
        "id": evidence_ref(doc.get("sequence", 0)),
        "source": doc.get("source"),
        "finding_type": doc.get("finding_type"),
        "category": _clean(doc.get("category"), FIELD_LIMITS["category"], counters),
        "title": _clean(doc.get("title"), FIELD_LIMITS["title"], counters),
        "target_component": _clean(
            doc.get("target_component"), FIELD_LIMITS["target_component"], counters
        ),
        "status": doc.get("status"),
        "expected": _clean(doc.get("expected"), FIELD_LIMITS["expected"], counters),
        "actual": _clean(doc.get("actual"), FIELD_LIMITS["actual"], counters),
        "tool_severity": doc.get("tool_severity"),
    }
    if payload.get("cwe"):
        item["cwe"] = _clean(payload["cwe"], 20, counters)
    return item


def build_evidence_context(
    assessment: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    max_items: int,
    max_chars: int,
) -> EvidenceContext:
    """Compact, sanitised, size-bounded context. Deterministic for a given input."""
    counters = {"redactions": 0, "truncated": 0}
    ordered = sorted(evidence, key=lambda doc: (doc.get("sequence", 0), str(doc.get("_id", ""))))

    compact = [(doc, _compact_evidence(doc, counters)) for doc in ordered]

    # Choose what to drop, least informative first, until within budget.
    drop_order = sorted(
        compact,
        key=lambda pair: (_OMIT_ORDER.get(str(pair[0].get("status")), 2), -pair[0].get("sequence", 0)),
    )
    # Serialised size of each item (+1 for the separating comma), so the
    # budget is tracked incrementally instead of re-serialising every time.
    sizes = {id(item): len(json.dumps(item, ensure_ascii=False)) + 1 for _, item in compact}
    total_chars = sum(sizes.values()) + 1
    dropped: set[int] = set()
    omitted: list[dict[str, Any]] = []

    for doc, item in drop_order:
        if len(compact) - len(dropped) <= max_items and total_chars <= max_chars:
            break
        dropped.add(id(item))
        total_chars -= sizes[id(item)]
        omitted.append(
            {
                "ref": item["id"],
                "evidence_id": doc.get("evidence_id"),
                "reason": "context size limit",
            }
        )

    kept = [(doc, item) for doc, item in compact if id(item) not in dropped]

    refs = {
        item["id"]: EvidenceRef(
            ref=item["id"],
            evidence_id=str(doc.get("evidence_id")),
            finding_type=str(doc.get("finding_type")),
            tool_severity=doc.get("tool_severity"),
            target_component=str(doc.get("target_component") or ""),
        )
        for doc, item in kept
    }

    return EvidenceContext(
        assessment=_compact_assessment(assessment, counters),
        items=[item for _, item in kept],
        refs=refs,
        omitted=sorted(omitted, key=lambda entry: entry["ref"]),
        total_evidence=len(evidence),
        truncated_fields=counters["truncated"],
        redactions=counters["redactions"],
    )
