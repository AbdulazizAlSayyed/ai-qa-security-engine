"""Deterministic validation of an extraction answer.

The model is never trusted because it returned JSON. An answer is accepted
only when every check below passes; nothing is repaired, dropped or
"fixed up", because a half-accepted set of proposals is worse than none - a
reviewer would have no way to know which half they were reading.

1. It parses as a single JSON object.
2. It matches :class:`RequirementExtractionOutput` exactly - required fields,
   the MoSCoW vocabulary, no extra keys. An invented ``key``, ``id`` or
   ``status`` fails here, which is what stops the model choosing an identity.
3. No two candidates have the same title (case-insensitively). Near-duplicate
   proposals waste the reviewer's attention, and the prompt already forbids
   splitting one statement into two.
4. No field carries a credential-shaped string. A BRD is exactly the kind of
   document that has a password pasted into it, and a candidate is on its way
   to a reviewer's screen.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.engines.requirements.models import RequirementExtractionOutput

#: The same spellings ``app.schemas.requirement`` refuses on the way in.
#: Checked here as well because a candidate is shown to a human before it
#: ever reaches that schema.
_CREDENTIAL_MARKERS = (
    "password=",
    "password:",
    "passwd=",
    "secret=",
    "secret:",
    "token=",
    "api_key=",
    "apikey=",
    "authorization: bearer ",
)

_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*)\n\s*```\s*$", re.DOTALL | re.IGNORECASE)


class ExtractionValidationError(Exception):
    """The model's answer was rejected. ``code`` is machine-readable."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the answer. A single fenced ```json block is unwrapped; nothing else is."""
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        data = json.loads(candidate)
    except ValueError as exc:
        where = f" ({exc.msg} at char {exc.pos})" if isinstance(exc, json.JSONDecodeError) else ""
        raise ExtractionValidationError(
            "invalid_json", f"The model's answer is not valid JSON{where}."
        ) from exc
    if not isinstance(data, dict):
        raise ExtractionValidationError(
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


def _credential_shaped(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _CREDENTIAL_MARKERS)


def validate_extraction(text: str) -> RequirementExtractionOutput:
    """Validate the model's answer. Returns it unchanged, or raises."""
    data = parse_json_object(text)

    try:
        output = RequirementExtractionOutput.model_validate(data)
    except ValidationError as exc:
        problems = _schema_problems(exc)
        raise ExtractionValidationError(
            "schema_violation",
            f"The model's answer does not match the extraction schema ({len(problems)} "
            f"problem{'' if len(problems) == 1 else 's'}): {'; '.join(problems[:5])}",
            {"problems": problems},
        ) from exc

    seen: set[str] = set()
    duplicates: list[str] = []
    for candidate in output.candidates:
        normalized = " ".join(candidate.title.split()).lower()
        if normalized in seen:
            duplicates.append(candidate.title)
        seen.add(normalized)
    if duplicates:
        raise ExtractionValidationError(
            "duplicate_candidate_title",
            "Two candidates state the same requirement: "
            f"{', '.join(sorted(set(duplicates))[:5])}.",
            {"titles": sorted(set(duplicates))},
        )

    for index, candidate in enumerate(output.candidates, start=1):
        texts = [
            candidate.title,
            candidate.description,
            candidate.source_reference,
            candidate.area,
            candidate.note,
            *candidate.acceptance_criteria,
        ]
        if any(_credential_shaped(value) for value in texts):
            # Deliberately does not repeat the offending value.
            raise ExtractionValidationError(
                "credential_in_candidate",
                f"Candidate {index} contains something shaped like a credential, so the "
                "whole extraction was rejected. Remove it from the document and try again.",
                {"candidate_index": index},
            )

    for note in output.notes:
        if _credential_shaped(note):
            raise ExtractionValidationError(
                "credential_in_candidate",
                "An extraction note contains something shaped like a credential, so the "
                "whole extraction was rejected.",
            )

    return output
