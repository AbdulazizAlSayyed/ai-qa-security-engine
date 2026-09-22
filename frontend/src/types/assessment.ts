/** Mirrors backend/app/schemas/assessment.py. Keep the two in step. */

import type { CorrelationSummary } from "@/types/issues";
import type { RecommendationSummary } from "@/types/recommendations";
import type { TargetType } from "@/types/target";

export const ASSESSMENT_STATES = [
  "created",
  "running",
  "qa_running",
  "security_running",
  "normalizing",
  "analyzing",
  "completed",
  "failed",
] as const;

export type AssessmentState = (typeof ASSESSMENT_STATES)[number];

/** Did an engine stage execute? Never "did the target pass". */
export type StageStatus = "pending" | "running" | "completed" | "failed";

export type EvidenceType = "qa" | "security";

/**
 * passed / failed: what the check or scanner reported.
 * skipped: the engine explicitly did not run the check.
 * error: the check could not execute - an engine fact, not a target fact.
 * observed: recorded but not asserted on; later phases judge it.
 */
export type EvidenceStatus = "passed" | "failed" | "skipped" | "error" | "observed";

export interface StateTransition {
  state: AssessmentState;
  timestamp: string;
  message: string | null;
}

export interface Evidence {
  id: string;
  evidence_id: string;
  assessment_id: string;
  sequence: number;
  source: string;
  finding_type: EvidenceType;
  category: string;
  title: string;
  target_component: string;
  status: EvidenceStatus;
  expected: string | null;
  actual: string | null;
  tool_severity: string | null;
  source_run_id: string | null;
  source_finding_id: string | null;
  evidence_payload: Record<string, unknown>;
  timestamp: string;
}

export interface AssessmentSummary {
  qa: { total: number; passed: number; failed: number; skipped: number; error: number };
  security: {
    total: number;
    high: number;
    medium: number;
    low: number;
    informational: number;
  };
  /** Failed QA checks plus security findings of every severity. */
  total_findings: number;
  evidence_total: number;
}

export interface CoverageItem {
  source: string;
  status: string;
  detail: string | null;
}

export interface Assessment {
  id: string;
  target_id: string;
  target_name: string;
  target_base_url: string;
  target_api_url: string | null;
  target_type: TargetType;

  status: AssessmentState;
  state_history: StateTransition[];
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;

  /** Ids of the raw runs; the runs live in their own collections. */
  qa_run_id: string | null;
  qa_status: StageStatus;
  qa_run_status: string | null;
  qa_error: string | null;

  security_run_id: string | null;
  security_status: StageStatus;
  security_run_status: string | null;
  security_error: string | null;

  partial: boolean;
  security_coverage: CoverageItem[];
  evidence_count: number;
  summary: AssessmentSummary;
  /** Phase 5: attached after the fact; never changes the technical result. */
  ai_analysis_status: "not_analyzed" | "running" | "completed" | "failed";
  ai_analysis_id: string | null;
  /** Phase 6: last correlation & prioritization run (derived metadata). */
  correlation: CorrelationSummary | null;
  /** Phase 8: last advisory recommendation generation (derived metadata). */
  recommendation: RecommendationSummary | null;
  error: string | null;
}
