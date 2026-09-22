"""Frontend <-> backend contract for the AI analysis types.

The frontend has no test runner of its own, and TypeScript only checks the
frontend against itself. This reads the interfaces in
``frontend/src/types/aiAnalysis.ts`` and requires their field names to match
the Pydantic models the API actually serialises, so a renamed or added field
on either side fails here instead of rendering ``undefined`` in the UI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.engines.ai.models import AIAnalysisResult, AIFinding
from app.schemas.ai_analysis import (
    AIAnalysisResponse,
    AIAnalysisView,
    AnalysisContextInfo,
    AnalysisError,
    OmittedEvidence,
)
from app.engines.remediation import models as remediation
from app.schemas import dashboard, recommendation, report, retest
from app.schemas.assessment import AssessmentResponse
from app.schemas.correlation import (
    CorrelationGroupResponse,
    CorrelationRunResponse,
    CorrelationSummary,
)
from app.schemas.issue import IssueAIFinding, IssueResponse, ScoreFactor
from app.schemas.target import (
    AuthenticationProfile,
    SecurityPolicy,
    TargetCreate,
    TargetDeleteResponse,
    TargetResponse,
)
from app.schemas.test_account import (
    TestAccountCreate,
    TestAccountDeleteResponse,
    TestAccountResponse,
)

FRONTEND_TYPES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types"


def interface_fields(source: str, name: str) -> set[str]:
    match = re.search(rf"export interface {name} \{{(.*?)\n\}}", source, re.DOTALL)
    assert match, f"interface {name} not found"
    return set(re.findall(r"^\s*(\w+)\??:", match.group(1), re.MULTILINE))


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("AIFinding", AIFinding),
        ("AIAnalysisResult", AIAnalysisResult),
        ("OmittedEvidence", OmittedEvidence),
        ("AnalysisContextInfo", AnalysisContextInfo),
        ("AnalysisError", AnalysisError),
        ("AIAnalysis", AIAnalysisResponse),
        ("AIAnalysisView", AIAnalysisView),
    ],
)
def test_ai_types_match_the_api(interface: str, model) -> None:
    source = (FRONTEND_TYPES / "aiAnalysis.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("ScoreFactor", ScoreFactor),
        ("IssueAIFinding", IssueAIFinding),
        ("Issue", IssueResponse),
        ("CorrelationSummary", CorrelationSummary),
        ("CorrelationGroup", CorrelationGroupResponse),
        ("CorrelationRun", CorrelationRunResponse),
    ],
)
def test_issue_types_match_the_api(interface: str, model) -> None:
    source = (FRONTEND_TYPES / "issues.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("QaCounts", dashboard.QaCounts),
        ("SecurityCounts", dashboard.SecurityCounts),
        ("PriorityCounts", dashboard.PriorityCounts),
        ("AssessmentCounts", dashboard.AssessmentCounts),
        ("IssueSummary", dashboard.IssueSummary),
        ("TargetCounts", dashboard.TargetCounts),
        ("HistoryItem", dashboard.HistoryItem),
        ("TrendPoint", dashboard.TrendPoint),
        ("Dashboard", dashboard.DashboardResponse),
    ],
)
def test_dashboard_types_match_the_api(interface: str, model) -> None:
    source = (FRONTEND_TYPES / "dashboard.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("RetestCheck", remediation.RetestCheck),
        ("RetestSpecification", remediation.RetestSpecification),
        ("Recommendation", recommendation.RecommendationResponse),
        ("GenerationError", recommendation.GenerationError),
        ("RecommendationSummary", recommendation.RecommendationSummary),
        ("RecommendationSet", recommendation.RecommendationSet),
        ("RecommendationsView", recommendation.RecommendationsView),
    ],
)
def test_recommendation_types_match_the_api(interface: str, model) -> None:
    source = (FRONTEND_TYPES / "recommendations.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("RetestPlanInfo", retest.RetestPlanInfo),
        ("RetestSourceRun", retest.SourceRun),
        ("RetestObservation", retest.RetestObservation),
        ("RetestResultSummary", retest.ResultSummary),
        ("RetestError", retest.RetestError),
        ("Retest", retest.RetestResponse),
    ],
)
def test_retest_types_match_the_api(interface: str, model) -> None:
    source = (FRONTEND_TYPES / "retests.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("ReportArtifact", report.ReportArtifact),
        ("ReportSourceSnapshot", report.ReportSourceSnapshot),
        ("TraceabilityErrorItem", report.TraceabilityErrorItem),
        ("ReportTraceability", report.ReportTraceability),
        ("RetestCounts", report.RetestCounts),
        ("ReportSummary", report.ReportSummary),
        ("ReportError", report.ReportError),
        ("Report", report.ReportResponse),
    ],
)
def test_report_types_match_the_api(interface: str, model) -> None:
    source = (FRONTEND_TYPES / "reports.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


def test_assessment_type_matches_the_api() -> None:
    source = (FRONTEND_TYPES / "assessment.ts").read_text(encoding="utf-8")
    assert interface_fields(source, "Assessment") == set(AssessmentResponse.model_fields)


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("AuthenticationProfile", AuthenticationProfile),
        ("SecurityPolicy", SecurityPolicy),
        ("Target", TargetResponse),
        ("TargetCreate", TargetCreate),
        ("TargetDeleteResult", TargetDeleteResponse),
    ],
)
def test_target_profile_types_match_the_api(interface: str, model) -> None:
    """Phase 12 added two nested blocks to the target, which is exactly the
    shape of change that renders as ``undefined`` in the UI when one side
    drifts."""
    source = (FRONTEND_TYPES / "target.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


@pytest.mark.parametrize(
    ("interface", "model"),
    [
        ("TestAccount", TestAccountResponse),
        ("TestAccountCreate", TestAccountCreate),
        ("TestAccountDeleteResult", TestAccountDeleteResponse),
    ],
)
def test_test_account_types_match_the_api(interface: str, model) -> None:
    source = (FRONTEND_TYPES / "testAccount.ts").read_text(encoding="utf-8")
    assert interface_fields(source, interface) == set(model.model_fields)


def test_no_frontend_type_declares_a_credential_field() -> None:
    """The browser is never given a place to hold a secret.

    A field named password/secret/token on any of these interfaces would mean
    the API had started returning one, which is the failure this whole design
    is built to prevent.

    Only interface bodies are inspected. The enum label maps in the same
    files legitimately contain keys like ``cookie`` (a place a target keeps
    its token), and those are display strings, not fields carrying a value.
    """
    forbidden = {"password", "secret", "token", "cookie"}
    for filename in ("target.ts", "testAccount.ts"):
        source = (FRONTEND_TYPES / filename).read_text(encoding="utf-8")
        interfaces = re.findall(r"export interface (\w+) \{", source)
        assert interfaces, f"{filename} declares no interfaces"
        for interface in interfaces:
            leaked = interface_fields(source, interface) & forbidden
            assert not leaked, f"{filename}::{interface} declares {sorted(leaked)}"
