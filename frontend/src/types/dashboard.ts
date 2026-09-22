/** Mirrors backend/app/schemas/dashboard.py.
 *  A backend test (tests/test_frontend_contract.py) keeps the field names in step. */

import type { AssessmentState, StageStatus } from "@/types/assessment";

export interface QaCounts {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  error: number;
}

/** By the scanner's own severity. There is no "critical". */
export interface SecurityCounts {
  total: number;
  high: number;
  medium: number;
  low: number;
  informational: number;
}

/** Counts of stored Phase 6 issues by priority. Priority is not a severity. */
export interface PriorityCounts {
  total: number;
  P1: number;
  P2: number;
  P3: number;
  P4: number;
}

export interface AssessmentCounts {
  total: number;
  by_status: Record<string, number>;
  completed: number;
  failed: number;
  running: number;
  analyzing: number;
  partial: number;
  ai_analyzed: number;
  correlated: number;
}

export interface IssueSummary {
  by_priority: PriorityCounts;
  by_type: Record<string, number>;
  assessments_with_issues: number;
}

export interface TargetCounts {
  total: number;
  enabled: number;
}

export interface HistoryItem {
  id: string;
  target_id: string;
  target_name: string;
  status: AssessmentState;
  partial: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  qa_status: StageStatus;
  security_status: StageStatus;
  qa: QaCounts;
  security: SecurityCounts;
  total_findings: number;
  evidence_count: number;
  ai_analysis_status: "not_analyzed" | "running" | "completed" | "failed";
  correlation_status: "not_correlated" | "running" | "completed" | "failed";
  issues: PriorityCounts;
}

/** One UTC day that has at least one assessment. */
export interface TrendPoint {
  date: string;
  assessments: number;
  completed: number;
  failed: number;
  partial: number;
  qa_failed: number;
  security: SecurityCounts;
  issues: PriorityCounts;
}

export interface Dashboard {
  generated_at: string;
  trend_days: number;
  history_limit: number;
  targets: TargetCounts;
  assessments: AssessmentCounts;
  qa: QaCounts;
  security: SecurityCounts;
  issues: IssueSummary;
  latest: HistoryItem | null;
  history: HistoryItem[];
  trends: TrendPoint[];
}
