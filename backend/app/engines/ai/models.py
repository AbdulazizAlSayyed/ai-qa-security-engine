"""The shapes AI analysis is allowed to take.

Two layers, on purpose:

* :class:`AIAnalysisOutput` is what the **model** must return. It is strict
  (``extra="forbid"``), so an unexpected key - an invented ``severity``, a
  ``risk_score`` - rejects the whole response instead of being ignored.
* :class:`AIAnalysisResult` is what the **platform** stores after validation.
  Evidence references are resolved to real ``evidence_id`` values and each
  finding's affected components are *derived from the cited evidence*, never
  taken from the model, so the model cannot invent an endpoint.

Nothing here scores, ranks or prioritises (Phase 6), and nothing recommends
fixes (Phase 8).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Version of the prompt + output contract. Bump it whenever either changes
#: so stored analyses are never ambiguous about what produced them.
ANALYSIS_VERSION = "1.0"

FindingType = Literal["qa", "security"]
Confidence = Literal["high", "medium", "low"]
#: The Phase 3 vocabulary, exactly. There is no "critical".
ToolSeverity = Literal["high", "medium", "low", "informational"]
#: ``insufficient_evidence`` is how the model says "this is worth noting but
#: the evidence does not establish a conclusion" instead of guessing.
FindingStatus = Literal["supported", "insufficient_evidence"]


class AnalysisStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# --- what the model must return --------------------------------------------


class AIFindingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    finding_id: str = Field(pattern=r"^AI-F-\d{3,}$")
    type: FindingType
    status: FindingStatus
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    impact: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    #: Required key; ``null`` when no cited record carries a tool severity.
    tool_severity: ToolSeverity | None
    #: Evidence references as supplied in the prompt (``EV-001``...).
    evidence_ids: list[str] = Field(min_length=1, max_length=200)
    uncertainty: str = Field(min_length=1, max_length=2000)


class AIAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    overall_assessment: str = Field(min_length=1, max_length=6000)
    findings: list[AIFindingOutput] = Field(max_length=100)
    evidence_gaps: list[str] = Field(max_length=50)
    limitations: list[str] = Field(max_length=50)


# --- what the platform stores ------------------------------------------------


class AIFinding(BaseModel):
    finding_id: str
    type: FindingType
    status: FindingStatus
    title: str
    description: str
    impact: str
    confidence: Confidence
    tool_severity: ToolSeverity | None
    #: Real ``evidence_id`` values from the ``evidence`` collection.
    evidence_ids: list[str]
    #: The same records as the short references the model saw.
    evidence_refs: list[str]
    #: Derived from the cited evidence's ``target_component``.
    affected_components: list[str]
    uncertainty: str


class AIAnalysisResult(BaseModel):
    overall_assessment: str
    findings: list[AIFinding]
    evidence_gaps: list[str]
    limitations: list[str]
