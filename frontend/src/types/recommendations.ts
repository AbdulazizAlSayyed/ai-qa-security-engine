/** Mirrors backend/app/schemas/recommendation.py and app/engines/remediation/models.py.
 *  A backend test (tests/test_frontend_contract.py) keeps the field names in step. */

export type RecommendationType =
  | "configuration_change"
  | "code_change"
  | "dependency_update"
  | "investigation"
  | "qa_test_improvement";

export type RetestType = "security_rescan" | "qa_recheck";
export type RetestScope = "origin" | "component";
export type PassCondition = "finding_absent" | "check_passes";

/** One existing tool check a later retest re-runs, taken from stored evidence. */
export interface RetestCheck {
  evidence_id: string;
  evidence_ref: string;
  source: string;
  finding_type: "qa" | "security";
  rule_id: string | null;
  title: string;
  target_component: string;
  baseline_status: string;
}

/** Specification only - nothing here has been run. */
export interface RetestSpecification {
  retest_type: RetestType;
  scope: RetestScope;
  target_id: string;
  target_component: string;
  issue_id: string;
  match_key: string;
  correlation_rule: string;
  pass_condition: PassCondition;
  checks: RetestCheck[];
  preconditions: string[];
  expected_result: string;
  pass_criteria: string;
  fail_criteria: string;
}

export interface Recommendation {
  id: string;
  recommendation_id: string;
  recommendation_number: number;
  assessment_id: string;
  target_id: string;
  ai_analysis_id: string;
  generation_id: string;
  correlation_completed_at: string | null;
  issue_id: string;
  related_issue_ids: string[];
  issue_ids: string[];
  issue_type: "qa" | "security";
  issue_priority: string;
  type: RecommendationType;
  title: string;
  description: string;
  rationale: string;
  /** The model's confidence in its advice - not a severity or a priority. */
  confidence: "high" | "medium" | "low";
  /** Always "advisory": the platform never applies a recommendation. */
  advisory_status: "advisory";
  affected_components: string[];
  evidence_ids: string[];
  evidence_refs: string[];
  ai_finding_ids: string[];
  retest: RetestSpecification;
  recommendation_version: string;
  created_at: string;
  updated_at: string;
}

export interface GenerationError {
  category: string;
  message: string;
}

export interface RecommendationSummary {
  status: "running" | "completed" | "failed";
  generation_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  ai_analysis_id: string | null;
  correlation_completed_at: string | null;
  provider: string | null;
  model: string | null;
  recommendation_version: string | null;
  issues_supplied: number;
  issues_omitted: string[];
  evidence_supplied: number;
  evidence_omitted: number;
  redactions: number;
  recommendation_count: number;
  usage: Record<string, number>;
  error: GenerationError | null;
}

export interface RecommendationSet {
  ai_analysis_id: string;
  count: number;
  updated_at: string;
}

export interface RecommendationsView {
  assessment_id: string;
  status: "not_generated" | "running" | "completed" | "failed";
  generation: RecommendationSummary | null;
  current_ai_analysis_id: string | null;
  ai_analysis_id: string | null;
  is_current: boolean;
  sets: RecommendationSet[];
  recommendations: Recommendation[];
}
