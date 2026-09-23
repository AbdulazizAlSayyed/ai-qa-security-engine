"""Request and response schemas for the requirements registry.

Two rules shape this module.

**A requirement is a statement, not a secret.** ``extra="forbid"`` means a
client cannot smuggle an unexpected key in, and every free-text field is
checked for the credential spellings Phase 12 already refuses, so a BRD
paragraph containing ``password=hunter2`` is rejected rather than stored.
The same check runs over AI-extracted candidates before they are ever shown,
because the document a candidate came from is outside this platform's
control.

**The client never chooses the key.** ``key`` and ``key_number`` are absent
from every input schema. The service allocates ``REQ-NNN`` per target, which
is what makes the reference stable and monotonic - and what stops an AI, or
anything else, from picking its own database identity.

Acceptance criterion ids work the same way: a client may send back an ``id``
it was given, and the service honours it, but a criterion with no id gets the
next free ``AC-NNN`` from the requirement's own series. Numbers are never
reused, so a reference written down today still means the same criterion
after five edits.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.models.requirement import CRITERION_PATTERN

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 4000
MAX_SOURCE_REFERENCE_LENGTH = 300
MAX_AREA_LENGTH = 80
MAX_CRITERION_TEXT_LENGTH = 1000
MAX_CRITERIA = 50

#: Same markers Phase 12 refuses in a test account's free text. A requirement
#: is written by a human from a document, and a document is exactly where a
#: credential ends up pasted by accident.
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


class RequirementSource(str, Enum):
    """Where the statement came from.

    Not a workflow and not a permission - a provenance label. ``brd`` and
    ``openapi`` mean "a human approved a candidate that was extracted from
    that kind of document", never "a machine published this".
    """

    MANUAL = "manual"
    USER_STORY = "user_story"
    BRD = "brd"
    OPENAPI = "openapi"


class RequirementStatus(str, Enum):
    """Whether this statement is agreed.

    ``draft`` is the safe default: something written down but not yet signed
    off. ``deprecated`` keeps a requirement's history rather than deleting
    it, because a REQ key that vanishes breaks every reference to it.
    """

    DRAFT = "draft"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class RequirementPriority(str, Enum):
    """How important the requirement is.

    The platform's two existing vocabularies both describe *findings* -
    ``P1..P4`` for prioritised issues, ``high/medium/low/informational`` for
    tool severity - so neither is reused here: how badly a feature is wanted
    is a different question from how bad a defect is. This is a small closed
    enum of its own, and a requirement's priority never flows into an issue's.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RequirementArea(str, Enum):
    """What kind of expectation this is.

    A short, closed classification. It is deliberately not a taxonomy of the
    application's features - ``area`` answers "what sort of requirement is
    this", and the feature it belongs to is already in the title and the
    source reference.
    """

    FUNCTIONAL = "functional"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    SECURITY = "security"
    USABILITY = "usability"
    PERFORMANCE = "performance"
    DATA = "data"
    API = "api"
    UI = "ui"


def reject_credentials_in_text(value: str | None, field_name: str) -> str | None:
    """Keep requirement text free of credentials.

    Refuses the obvious spellings and says why. It does not make pasting a
    secret impossible; it makes the common accident loud instead of silent.
    """
    if value is None:
        return None
    lowered = value.lower()
    for marker in _CREDENTIAL_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"{field_name} must not contain credentials. Describe the behaviour, "
                "and keep secrets in environment variables the platform never stores."
            )
    return value


def blank_is_empty(value: Any) -> Any:
    """Treat an all-whitespace string as the empty string."""
    if isinstance(value, str) and not value.strip():
        return ""
    return value


class AcceptanceCriterion(BaseModel):
    """One checkable statement belonging to one requirement.

    ``id`` is optional on the way in and always present on the way out. A
    client that echoes back the id it was given keeps that criterion's
    identity; a client that sends ``null`` (or omits it) is asking for a new
    one, and the service allocates the next free number in the requirement's
    own series.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    id: str | None = Field(
        default=None,
        description="Stable AC-NNN reference within this requirement. Server-allocated.",
        examples=["AC-001"],
    )
    text: str = Field(
        min_length=1,
        max_length=MAX_CRITERION_TEXT_LENGTH,
        description="One condition that must hold for the requirement to be met.",
        examples=["A guest adding an out-of-stock item is shown an error and no order is created."],
    )

    @field_validator("id", mode="before")
    @classmethod
    def _id_is_a_reference(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("an acceptance criterion id is an AC-NNN reference.")
        cleaned = value.strip()
        if not cleaned:
            return None
        if not CRITERION_PATTERN.match(cleaned):
            raise ValueError(
                "an acceptance criterion id looks like AC-001. Omit it to have one "
                "allocated."
            )
        return cleaned

    @field_validator("text")
    @classmethod
    def _no_credentials(cls, value: str) -> str:
        return reject_credentials_in_text(value, "acceptance criterion text") or ""


class RequirementBase(BaseModel):
    """The fields a client may supply when writing a requirement.

    ``key`` is not among them. The registry allocates it, so two clients
    creating requirements at the same moment cannot claim the same reference
    and no caller can choose its own.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        description="What the target must do, in one line.",
        examples=["Checkout rejects an order that exceeds available stock"],
    )
    description: str = Field(
        min_length=1,
        max_length=MAX_DESCRIPTION_LENGTH,
        description="The statement in full, in the author's own words. Required.",
        examples=[
            "The system must reject an order whose quantity exceeds available stock."
        ],
    )
    source: RequirementSource = Field(
        default=RequirementSource.MANUAL,
        description="Where the statement came from. Provenance, not permission.",
    )
    source_reference: str = Field(
        default="",
        max_length=MAX_SOURCE_REFERENCE_LENGTH,
        description="Where to find it in that source - a section, a story id, an operation id.",
        examples=["BRD section 4.2", "POST /api/orders"],
    )
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        default_factory=list,
        max_length=MAX_CRITERIA,
        description="The conditions that make this requirement checkable.",
    )
    area: RequirementArea = Field(
        default=RequirementArea.FUNCTIONAL,
        description="What kind of expectation this is.",
    )
    priority: RequirementPriority = Field(
        default=RequirementPriority.MEDIUM,
        description="How important this requirement is. Not a defect severity.",
    )
    status: RequirementStatus = Field(
        default=RequirementStatus.DRAFT,
        description="Whether the statement is agreed. New requirements start as drafts.",
    )

    @field_validator("source_reference", mode="before")
    @classmethod
    def _blank_is_empty(cls, value: Any) -> Any:
        return blank_is_empty(value)

    @field_validator("title", "description", "source_reference")
    @classmethod
    def _no_credentials_in_text(cls, value: str, info: ValidationInfo) -> str:
        return reject_credentials_in_text(value, info.field_name or "field") or ""


class RequirementCreate(RequirementBase):
    """Payload for ``POST /targets/{target_id}/requirements``.

    ``target_id`` is not a field: it comes from the path, so a requirement
    cannot be filed against a target other than the one addressed.
    """


class RequirementUpdate(BaseModel):
    """Payload for ``PATCH /targets/{target_id}/requirements/{requirement_id}``.

    Every field is optional; only what the client sends is written.
    ``target_id``, ``key`` and ``key_number`` are absent on purpose - a
    requirement belongs to the target it was written for, and its reference
    is permanent.

    ``acceptance_criteria`` is replaced whole rather than merged, because a
    partial merge cannot express "delete the second criterion". Ids the
    client echoes back survive the replacement; anything without one is new.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str | None = Field(
        default=None, min_length=1, max_length=MAX_DESCRIPTION_LENGTH
    )
    source: RequirementSource | None = None
    source_reference: str | None = Field(default=None, max_length=MAX_SOURCE_REFERENCE_LENGTH)
    acceptance_criteria: list[AcceptanceCriterion] | None = Field(
        default=None, max_length=MAX_CRITERIA
    )
    area: RequirementArea | None = None
    priority: RequirementPriority | None = None
    status: RequirementStatus | None = None

    @field_validator("source_reference", mode="before")
    @classmethod
    def _blank_is_empty(cls, value: Any) -> Any:
        return blank_is_empty(value)

    @field_validator("title", "description", "source_reference")
    @classmethod
    def _no_credentials_in_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        return reject_credentials_in_text(value, info.field_name or "field")

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(mode="json", exclude_unset=True)


class RequirementResponse(BaseModel):
    """A requirement as the API exposes it."""

    id: str = Field(description="String form of the MongoDB ObjectId.")
    target_id: str
    key: str = Field(description="Target-scoped human reference, REQ-001 onwards.")
    key_number: int = Field(description="The integer inside the key. Orders the registry.")
    title: str
    description: str
    source: RequirementSource
    source_reference: str
    acceptance_criteria: list[AcceptanceCriterion]
    area: RequirementArea
    priority: RequirementPriority
    status: RequirementStatus
    extraction_id: str = Field(
        default="",
        description=(
            "The extraction a reviewer accepted this from, when it came from one. "
            "Empty for a hand-written requirement. An audit breadcrumb back to the "
            "logged extraction run, not a claim that anything was verified."
        ),
    )
    created_at: datetime
    updated_at: datetime


class RequirementDeleteResponse(BaseModel):
    """Confirmation that a requirement was removed."""

    deleted: bool = True
    id: str
    key: str


# --- candidates -------------------------------------------------------------
#
# A candidate is a *proposal*. It has no key, no id, no timestamps and no row
# in MongoDB, and nothing in this platform can turn one into a requirement by
# itself. The only path from candidate to requirement runs through a human
# who reads it, edits it if they disagree, and posts back the ones they
# accept - at which point it is an ordinary create and is validated as one.


MAX_DOCUMENT_CHARS = 100_000
MAX_CANDIDATES = 50
MAX_IMPORT = 100


class RequirementCandidate(BaseModel):
    """A proposed requirement, awaiting human review.

    Acceptance criteria are plain strings here rather than
    :class:`AcceptanceCriterion` objects: a candidate has no identity yet, so
    numbering its criteria would imply a permanence it does not have. Ids are
    allocated when - and only when - a human accepts it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    source_reference: str = Field(default="", max_length=MAX_SOURCE_REFERENCE_LENGTH)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=MAX_CRITERIA)
    area: RequirementArea = RequirementArea.FUNCTIONAL
    priority: RequirementPriority = RequirementPriority.MEDIUM
    note: str = Field(
        default="",
        max_length=MAX_CRITERION_TEXT_LENGTH,
        description="What the extractor based this on. For the reviewer; never stored.",
    )


class RequirementExtractionRequest(BaseModel):
    """Payload for ``POST /targets/{target_id}/requirements/extract-from-brd``.

    The document is read, used to build one prompt, and thrown away. It is
    not written to MongoDB, not logged and not returned, because a business
    document belongs to whoever pasted it and this platform has no reason to
    keep a copy.
    """

    model_config = ConfigDict(extra="forbid")

    document: str = Field(
        min_length=1,
        max_length=MAX_DOCUMENT_CHARS,
        description="The BRD text to read. Untrusted data - never instructions.",
    )


class OpenApiImportRequest(BaseModel):
    """Payload for ``POST /targets/{target_id}/requirements/extract-from-openapi``.

    The document itself, as JSON or YAML text. Nothing is fetched: the
    platform never contacts the API this document describes, and an OpenAPI
    ``servers`` entry is read as text, not as somewhere to send a request.
    """

    model_config = ConfigDict(extra="forbid")

    document: str = Field(
        min_length=1,
        max_length=MAX_DOCUMENT_CHARS,
        description="An OpenAPI 3.x document, JSON or YAML. Parsed offline.",
    )


class RequirementExtractionResponse(BaseModel):
    """Candidates for a human to review. Nothing here has been stored."""

    target_id: str
    source: RequirementSource = Field(
        description="What kind of document these came from - brd or openapi."
    )
    extraction_id: str = Field(description="Identifies this extraction in the logs.")
    provider: str = Field(
        default="",
        description="Which AI provider produced these, or empty for an offline import.",
    )
    model: str = Field(default="", description="Which model, or empty for an offline import.")
    candidates: list[RequirementCandidate]
    notes: list[str] = Field(
        default_factory=list,
        description="What the extractor could not do, in plain words. Never a guess.",
    )
    document_chars: int = Field(description="How much of the document was read.")


class RequirementImportRequest(BaseModel):
    """Payload for ``POST /targets/{target_id}/requirements/import``.

    This is the human approval step, and it is an ordinary create in
    disguise: every entry is a full :class:`RequirementCreate` and is
    validated exactly as one. Candidates a reviewer rejected are simply not
    in the list, and edits a reviewer made are what arrives here.
    """

    model_config = ConfigDict(extra="forbid")

    requirements: list[RequirementCreate] = Field(min_length=1, max_length=MAX_IMPORT)
    extraction_id: str = Field(
        default="",
        max_length=64,
        pattern=r"^[a-f0-9]{0,64}$",
        description=(
            "The extraction these were reviewed from, echoed back so each stored "
            "requirement can be traced to the run that proposed it."
        ),
    )


class RequirementImportResponse(BaseModel):
    """What the approval step created, with the keys it allocated."""

    created: list[RequirementResponse]
    count: int
