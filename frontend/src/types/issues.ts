/** Mirrors backend/app/schemas/issue.py and app/schemas/correlation.py.
 *  A backend test (tests/test_frontend_contract.py) keeps the field names in step. */

/** Derived ranking of an issue. Not a severity. */
export type Priority = "P1" | "P2" | "P3" | "P4";
export const PRIORITIES: readonly Priority[] = ["P1", "P2", "P3", "P4"];

export type IssueType = "qa" | "security";
export type IssueToolSeverity = "high" | "medium" | "low" | "informational";
export type ScoreFactorName = "base" | "spread" | "repetition" | "corroboration" | "ai_support";

export interface ScoreFactor {
  factor: ScoreFactorName;
  points: number;
  detail: string;
}

/** A finding from a completed AI analysis that cites the issue's evidence. */
export interface IssueAIFinding {
  finding_id: string;
  title: string;
  status: string;
  confidence: string;
  evidence_refs: string[];
}

export interface Issue {
  id: string;
  /** ISSUE-###, unique within the assessment and stable across re-runs. */
  issue_id: string;
  issue_number: number;
  assessment_id: string;
  correlation_group_id: string;
  group_key: string;
  type: IssueType;
  title: string;
  description: string;
  priority: Priority;
  priority_score: number;
  priority_reasons: string[];
  score_factors: ScoreFactor[];
  priority_model_version: string;
  /** Most severe tool severity among the evidence, as the scanner reported it. */
  tool_severity: IssueToolSeverity | null;
  /** Confidence of the supporting AI finding that was counted, if any. */
  confidence: "high" | "medium" | "low" | null;
  affected_components: string[];
  sources: string[];
  correlation_rule: string;
  evidence_ids: string[];
  evidence_refs: string[];
  evidence_count: number;
  ai_analysis_id: string | null;
  ai_finding_ids: string[];
  ai_findings: IssueAIFinding[];
  created_at: string;
  updated_at: string;
}

export type CorrelationStatus = "running" | "completed" | "failed";

export interface CorrelationSummary {
  status: CorrelationStatus;
  started_at: string | null;
  completed_at: string | null;
  correlation_version: string | null;
  priority_model_version: string | null;
  ai_analysis_id: string | null;
  evidence_total: number;
  evidence_considered: number;
  evidence_excluded: Record<string, number>;
  ai_references_ignored: number;
  group_count: number;
  issue_count: number;
  priority_counts: Record<string, number>;
  error: string | null;
}

export interface CorrelationGroup {
  id: string;
  /** CG-###, unique within the assessment. */
  correlation_group_id: string;
  group_number: number;
  assessment_id: string;
  group_key: string;
  correlation_rule: string;
  correlation_rule_description: string;
  correlation_reason: string;
  correlation_version: string;
  finding_type: IssueType;
  identity: string;
  target_component: string;
  affected_components: string[];
  categories: string[];
  sources: string[];
  evidence_statuses: string[];
  tool_severity: string | null;
  representative_title: string;
  representative_evidence_id: string;
  evidence_ids: string[];
  evidence_refs: string[];
  evidence_count: number;
  created_at: string;
  updated_at: string;
}

export interface CorrelationRun {
  assessment_id: string;
  correlation: CorrelationSummary;
  issues: Issue[];
}
