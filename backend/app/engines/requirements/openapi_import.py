"""Offline reading of an OpenAPI document into requirement candidates.

**Nothing here touches a network.** The document is text the operator
supplied; it is parsed, walked and turned into proposals. A ``servers`` entry
is read as a string and never used as somewhere to send a request, ``$ref``
is never dereferenced (a remote ``$ref`` would be a fetch, so none happens at
all), and no operation described by the document is ever executed. This
module imports no HTTP client, and that is deliberate.

No model is involved either. An API specification already states what the
API offers, so turning it into candidates is a parse, not an inference -
which is why these candidates carry no AI provenance and cost nothing.

What it produces is still only a *candidate*. An OpenAPI document says what
endpoints exist; it does not say what the business wants, so a human decides
which of these are requirements worth keeping.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import yaml

#: Operations worth stating as requirements. ``trace`` is omitted: it is a
#: diagnostic, not behaviour anyone writes a requirement about.
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch")

MAX_CANDIDATES = 50
MAX_CRITERIA_PER_OPERATION = 12
MAX_TEXT = 300


class OpenApiDocumentError(Exception):
    """The supplied text is not an OpenAPI document this importer can read."""


def _load(document: str) -> Mapping[str, Any]:
    """Parse JSON or YAML. ``safe_load`` only - a document never builds objects."""
    text = document.strip()
    if not text:
        raise OpenApiDocumentError("The document is empty.")
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise OpenApiDocumentError(
                "The document is neither valid JSON nor valid YAML."
            ) from exc
    if not isinstance(data, Mapping):
        raise OpenApiDocumentError("The document does not parse to an object.")
    return data


def _version(data: Mapping[str, Any]) -> str:
    version = data.get("openapi")
    if isinstance(version, str) and version.startswith("3."):
        return version
    if "swagger" in data:
        raise OpenApiDocumentError(
            "This is a Swagger 2.0 document. Convert it to OpenAPI 3.x first - "
            "guessing at the differences would produce requirements the document "
            "does not state."
        )
    raise OpenApiDocumentError(
        "No OpenAPI 3.x version found. The document must have a top-level "
        '"openapi" field such as "3.0.3".'
    )


def _clip(value: Any, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


#: Every candidate from an OpenAPI document is an API-level expectation, so
#: they all get the same area. The document's own tags describe *features*,
#: which is a different question, so a tag is reported in the note for the
#: reviewer rather than forced into this vocabulary.
CANDIDATE_AREA = "api"

#: An API specification says nothing about business importance, so the
#: importer does not pretend to know it.
CANDIDATE_PRIORITY = "medium"


def _tag(operation: Mapping[str, Any]) -> str:
    tags = operation.get("tags")
    if isinstance(tags, list) and tags and isinstance(tags[0], str):
        return _clip(tags[0], 80)
    return ""


def _criteria(operation: Mapping[str, Any]) -> list[str]:
    """Acceptance criteria the document actually states.

    Only three things qualify: the documented response codes, whether a
    request body is required, and which parameters are required. Everything
    else in an operation object is description or implementation detail, and
    inventing a criterion from it would be exactly what this platform must
    not do.
    """
    criteria: list[str] = []

    responses = operation.get("responses")
    if isinstance(responses, Mapping):
        for code in sorted(str(key) for key in responses):
            entry = responses.get(code)
            description = ""
            if isinstance(entry, Mapping):
                description = _clip(entry.get("description"), 160)
            if description:
                criteria.append(f"Responds {code}: {description}.")
            else:
                criteria.append(f"Responds {code} where the specification says it does.")

    body = operation.get("requestBody")
    if isinstance(body, Mapping) and body.get("required") is True:
        criteria.append("Rejects a request that omits the required request body.")

    parameters = operation.get("parameters")
    if isinstance(parameters, list):
        required = [
            f"{_clip(p.get('name'), 60)} ({_clip(p.get('in'), 20)})"
            for p in parameters
            if isinstance(p, Mapping) and p.get("required") is True and p.get("name")
        ]
        if required:
            criteria.append(
                "Requires " + ", ".join(required[:6]) + " and rejects a request without them."
            )

    return criteria[:MAX_CRITERIA_PER_OPERATION]


def _contains_ref(value: Any, depth: int = 0) -> bool:
    """Is there a ``$ref`` anywhere in here? Never followed - only reported."""
    if depth > 8:
        return False
    if isinstance(value, Mapping):
        if "$ref" in value:
            return True
        return any(_contains_ref(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ref(item, depth + 1) for item in value)
    return False


def extract_candidates(document: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse an OpenAPI document into candidate dicts and reader's notes.

    Returns ``(candidates, notes)``. The candidates are plain dicts matching
    :class:`app.schemas.requirement.RequirementCandidate`; the notes say what
    the parser could not do, in the same spirit as the model's ``notes``.
    """
    data = _load(document)
    version = _version(data)

    paths = data.get("paths")
    if not isinstance(paths, Mapping) or not paths:
        raise OpenApiDocumentError(
            "The document declares no paths, so there is nothing to propose."
        )

    title = ""
    info = data.get("info")
    if isinstance(info, Mapping):
        title = _clip(info.get("title"), 80)

    candidates: list[dict[str, Any]] = []
    notes: list[str] = [
        f"Parsed offline from an OpenAPI {version} document"
        + (f" ({title})." if title else ".")
        + " Nothing was requested from the API it describes.",
        "An API specification does not state business importance, so every candidate "
        f"is {CANDIDATE_PRIORITY} and {CANDIDATE_AREA} until a reviewer says otherwise.",
    ]
    saw_ref = False
    skipped = 0

    for path in sorted(str(key) for key in paths):
        item = paths.get(path)
        if not isinstance(item, Mapping):
            continue
        for method in HTTP_METHODS:
            operation = item.get(method)
            if not isinstance(operation, Mapping):
                continue
            if len(candidates) >= MAX_CANDIDATES:
                skipped += 1
                continue

            saw_ref = saw_ref or _contains_ref(operation)
            verb = method.upper()
            summary = _clip(operation.get("summary"), 180)
            description = _clip(operation.get("description"), 1000)
            operation_id = _clip(operation.get("operationId"), 120)
            tag = _tag(operation)

            candidates.append(
                {
                    "title": summary or f"{verb} {path} is available",
                    "description": (
                        description
                        or summary
                        or f"The API exposes {verb} {path}, as stated by the OpenAPI document."
                    ),
                    "source_reference": operation_id or f"{verb} {path}",
                    "acceptance_criteria": _criteria(operation),
                    "area": CANDIDATE_AREA,
                    "priority": CANDIDATE_PRIORITY,
                    "note": (
                        f"Derived from the {verb} {path} operation"
                        + (f", tagged {tag!r} in the document" if tag else "")
                        + ". The specification describes the interface; whether this is "
                        "a business requirement is the reviewer's call."
                    ),
                }
            )

    if not candidates:
        raise OpenApiDocumentError(
            "The document declares paths but no operations this importer reads "
            f"({', '.join(HTTP_METHODS)})."
        )

    if skipped:
        notes.append(
            f"{skipped} further operation(s) were not proposed: the importer stops at "
            f"{MAX_CANDIDATES} candidates per document."
        )
    if saw_ref:
        notes.append(
            "Some operations use $ref. References are reported, never followed - "
            "resolving one could mean fetching a remote document - so criteria drawn "
            "from a referenced schema are absent rather than guessed."
        )

    return candidates, notes


def operation_count(document: str) -> int:
    """How many operations the document declares. Used by tests and messages."""
    data = _load(document)
    paths = data.get("paths")
    if not isinstance(paths, Mapping):
        return 0
    return sum(
        1
        for item in paths.values()
        if isinstance(item, Mapping)
        for method in HTTP_METHODS
        if isinstance(item.get(method), Mapping)
    )
