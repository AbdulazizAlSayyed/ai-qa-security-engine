"""The shapes a recommendation may take.

Two layers, as in Phase 5:

* :class:`RecommendationsOutput` is what the **model** must return. It is
  strict (``extra="forbid"``): an unexpected key - ``applied``, ``command``,
  ``severity`` - rejects the whole answer.
* :class:`Recommendation` is what the **platform** stores after validation.
  Issue and evidence references are resolved to real ids, affected
  components come from the issue, and every structural part of the retest
  specification (type, scope, engine checks, match key, pass condition) is
  derived from stored records - the model only contributes the human-readable
  criteria and the choice among values it was shown.

A recommendation is advisory. There is no field that says it was applied,
fixed or executed, and there never will be one in this model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Version of the prompt + output contract. Bump when either changes.
RECOMMENDATION_VERSION = "1.0"

RecommendationType = Literal[
    "configuration_change",
    "code_change",
    "dependency_update",
    "investigation",
    "qa_test_improvement",
]
Confidence = Literal["high", "medium", "low"]
#: The only lifecycle value. Recommendations are never executed by the platform.
AdvisoryStatus = Literal["advisory"]
ADVISORY: AdvisoryStatus = "advisory"

#: Which existing engine a Phase 9 retest re-runs.
RetestType = Literal["security_rescan", "qa_recheck"]
#: ``origin`` = the issue was grouped per origin (e.g. a missing header);
#: ``component`` = one endpoint / check / source location.
RetestScope = Literal["origin", "component"]
#: How Phase 9 decides PASS deterministically:
#: ``finding_absent`` - the issue's correlation key no longer appears;
#: ``check_passes``   - the same QA check reports ``passed``.
PassCondition = Literal["finding_absent", "check_passes"]

IssueId = Annotated[str, Field(pattern=r"^ISSUE-\d{3,}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]


# --- what the model must return ---------------------------------------------------


class RetestOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: Copied from the primary issue's affected components (or its scope).
    target_component: str = Field(min_length=1, max_length=500)
    #: EV-### references of the primary issue's evidence to re-verify.
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    preconditions: list[ShortText] = Field(max_length=10)
    expected_result: str = Field(min_length=1, max_length=1000)
    pass_criteria: str = Field(min_length=1, max_length=1000)
    fail_criteria: str = Field(min_length=1, max_length=1000)


class RecommendationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: The primary issue. At most one recommendation per issue.
    issue_id: IssueId
    related_issue_ids: list[IssueId] = Field(max_length=20)
    type: RecommendationType
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    #: EV-### references supporting the recommendation.
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    retest: RetestOutput


class RecommendationsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recommendations: list[RecommendationOutput] = Field(max_length=100)


# --- what the platform stores -----------------------------------------------------


class RetestCheck(BaseModel):
    """One existing tool check Phase 9 re-runs, taken from a stored evidence record."""

    evidence_id: str
    evidence_ref: str
    source: str
    finding_type: Literal["qa", "security"]
    rule_id: str | None = None
    title: str
    target_component: str
    #: The evidence status at the time of the assessment.
    baseline_status: str


class RetestSpecification(BaseModel):
    """Everything Phase 9 needs to re-run and judge one recommendation. Not executed here."""

    retest_type: RetestType
    scope: RetestScope
    target_id: str
    target_component: str
    issue_id: str
    #: The Phase 6 correlation key of the issue: a retest PASSes on
    #: ``finding_absent`` when no new evidence produces this key.
    match_key: str
    correlation_rule: str
    pass_condition: PassCondition
    checks: list[RetestCheck]
    preconditions: list[str]
    expected_result: str
    pass_criteria: str
    fail_criteria: str


class Recommendation(BaseModel):
    recommendation_id: str
    recommendation_number: int
    assessment_id: str
    target_id: str
    ai_analysis_id: str
    generation_id: str
    #: When the correlation that produced the issues completed (staleness check).
    correlation_completed_at: datetime | None = None
    issue_id: str
    related_issue_ids: list[str]
    issue_ids: list[str]
    #: Snapshot of the primary issue, copied for display; never changed here.
    issue_type: Literal["qa", "security"]
    issue_priority: str
    type: RecommendationType
    title: str
    description: str
    rationale: str
    #: The model's confidence in its advice - not a severity, not a priority.
    confidence: Confidence
    advisory_status: AdvisoryStatus = ADVISORY
    affected_components: list[str]
    evidence_ids: list[str]
    evidence_refs: list[str]
    ai_finding_ids: list[str]
    retest: RetestSpecification
    recommendation_version: str = RECOMMENDATION_VERSION
