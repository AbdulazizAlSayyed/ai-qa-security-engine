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
