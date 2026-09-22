/** Mirrors backend/app/schemas/retest.py.
 *  A backend test (tests/test_frontend_contract.py) keeps the field names in step. */

import type { PassCondition, RetestCheck, RetestScope, RetestType } from "@/types/recommendations";

/** Did the retest execute? Kept separate from the verdict. */
export type RetestStatus = "running" | "completed" | "failed";
/** What did it conclude? Only set when status is "completed". */
export type RetestVerdict = "PASS" | "FAIL";

export interface RetestPlanInfo {
  engine: "qa" | "security";
  components: string[];
  qa_checks: string[];
}

export interface RetestSourceRun {
  engine: "qa" | "security";
  run_id: string;
  status: string | null;
}

/** One new normalized result that decided the verdict (never stored as evidence). */
export interface RetestObservation {
  source: string | null;
  finding_type: string | null;
  title: string | null;
  target_component: string | null;
  status: string | null;
  tool_severity: string | null;
  correlation_key: string;
  source_run_id: string | null;
  source_finding_id: string | null;
}

export interface RetestResultSummary {
  engine: "qa" | "security";
  results_evaluated: number;
  matching_results: number;
  reason: string;
}

export interface RetestError {
  category: string;
  message: string;
}

export interface Retest {
  id: string;
  retest_id: string;
  retest_number: number;
  assessment_id: string;
  target_id: string;
  recommendation_id: string;
  recommendation_ref: string;
  ai_analysis_id: string;
  issue_id: string;
  correlation_group_id: string | null;
  type: RetestType;
  scope: RetestScope;
  target_component: string;
  match_key: string;
  pass_condition: PassCondition;
  checks: RetestCheck[];
  plan: RetestPlanInfo;
  status: RetestStatus;
  verdict: RetestVerdict | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  source_run_ids: string[];
  source_runs: RetestSourceRun[];
  matched_evidence_ids: string[];
  matched_evidence_refs: string[];
  observations: RetestObservation[];
  result_summary: RetestResultSummary | null;
  error: RetestError | null;
  retest_version: string;
  created_at: string;
  updated_at: string;
}
