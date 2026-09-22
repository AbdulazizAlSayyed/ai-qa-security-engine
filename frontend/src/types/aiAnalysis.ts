/** Mirrors backend/app/schemas/ai_analysis.py and app/engines/ai/models.py.
 *  A backend test (tests/test_frontend_contract.py) keeps the field names in step. */

export type AIAnalysisStatus = "created" | "running" | "completed" | "failed";
export type AIAnalysisViewStatus = "not_analyzed" | AIAnalysisStatus;

export type AIFindingType = "qa" | "security";
export type AIConfidence = "high" | "medium" | "low";
/** insufficient_evidence: worth noting, but the evidence does not settle it. */
export type AIFindingStatus = "supported" | "insufficient_evidence";
export type AIToolSeverity = "high" | "medium" | "low" | "informational";

export interface AIFinding {
  finding_id: string;
  type: AIFindingType;
  status: AIFindingStatus;
  title: string;
  description: string;
  impact: string;
  /** The model's confidence in its interpretation - not a severity. */
  confidence: AIConfidence;
  /** Copied from the cited evidence; validated server-side. */
  tool_severity: AIToolSeverity | null;
  /** Real evidence ids in this assessment's evidence collection. */
  evidence_ids: string[];
  /** The same records as the EV-### references the model saw. */
  evidence_refs: string[];
  /** Derived from the cited evidence, never from the model. */
  affected_components: string[];
  uncertainty: string;
}

export interface AIAnalysisResult {
  overall_assessment: string;
  findings: AIFinding[];
  evidence_gaps: string[];
  limitations: string[];
}

export interface OmittedEvidence {
  ref: string;
  evidence_id: string | null;
  reason: string;
}

export interface AnalysisContextInfo {
  total_evidence: number;
  supplied_evidence: number;
  omitted: OmittedEvidence[];
  truncated_fields: number;
  redactions: number;
}

export interface AnalysisError {
  category: string;
  message: string;
  details: Record<string, unknown>;
}

export interface AIAnalysis {
  id: string;
  analysis_id: string;
  assessment_id: string;
  target_id: string | null;
  provider: string;
  model: string;
  analysis_version: string;
  status: AIAnalysisStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  evidence_ids: string[];
  evidence_count: number;
  context: AnalysisContextInfo;
  usage: Record<string, number>;
  result: AIAnalysisResult | null;
  error: AnalysisError | null;
}

export interface AIAnalysisView {
  assessment_id: string;
  status: AIAnalysisViewStatus;
  latest: AIAnalysis | null;
  latest_completed: AIAnalysis | null;
}
