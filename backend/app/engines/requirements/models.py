"""The shape a model must return when reading a business document.

Strict on purpose (``extra="forbid"``): an invented ``key``, ``id``,
``status`` or ``req_id`` rejects the whole answer instead of being quietly
ignored. That is the mechanism by which the model cannot choose a database
identity - it has no field to put one in, and a field it made up fails
validation.

Nothing here has a key, an id or a timestamp. These are proposals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Version of the prompt + output contract. Bump it whenever either changes.
EXTRACTION_VERSION = "1.0"

#: The vocabularies from ``app.schemas.requirement``, restated as Literals so
#: the model's answer is checked against them directly. A value outside either
#: list fails validation rather than being mapped to something plausible.
CandidatePriority = Literal["low", "medium", "high", "critical"]
CandidateArea = Literal[
    "functional",
    "authentication",
    "authorization",
    "security",
    "usability",
    "performance",
    "data",
    "api",
    "ui",
]

MAX_CANDIDATES = 50
MAX_NOTES = 20


class RequirementCandidateOutput(BaseModel):
    """One proposed requirement as the model must write it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    #: Where in the supplied document this came from, in the document's own
    #: words - a heading, a section number, a story id. Required, because a
    #: proposal a reviewer cannot trace back is not reviewable.
    source_reference: str = Field(min_length=1, max_length=300)
    acceptance_criteria: list[str] = Field(max_length=50)
    area: CandidateArea
    priority: CandidatePriority
    #: Why the extractor believes this is a requirement, or what it was
    #: unsure about. Shown to the reviewer and then discarded.
    note: str = Field(max_length=1000)


class RequirementExtractionOutput(BaseModel):
    """The whole answer: proposals, plus what could not be read."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidates: list[RequirementCandidateOutput] = Field(max_length=MAX_CANDIDATES)
    #: Sections the model could not turn into a requirement, and why. This is
    #: how it says "this document does not state that" instead of inventing.
    notes: list[str] = Field(max_length=MAX_NOTES)
