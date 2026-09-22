/** Mirrors backend/app/schemas/report.py.
 *  A backend test (tests/test_frontend_contract.py) keeps the field names in step. */

export type ReportStatus = "running" | "completed" | "failed";

export interface ReportArtifact {
  format: "html" | "pdf";
  media_type: string;
  size_bytes: number;
  sha256: string;
  filename: string;
}

export interface ReportSourceSnapshot {
  assessment_id: string;
  assessment_status: string;
  partial: boolean;
  qa_run_id: string | null;
  security_run_id: string | null;
  evidence_count: number;
  ai_analysis_id: string | null;
  ai_analysis_status: string;
  correlation_status: string;
  correlation_version: string | null;
  priority_model_version: string | null;
  group_count: number;
  issue_count: number;
  recommendation_status: string;
  recommendation_set: string | null;
  recommendation_count: number;
  retest_count: number;
}

export interface TraceabilityErrorItem {
  relationship: string;
  source: string;
  reference: string;
  problem: string;
}

export interface ReportTraceability {
  status: "passed" | "failed";
  checked_at: string;
  links_checked: number;
  checks: Record<string, number>;
  errors: TraceabilityErrorItem[];
}

export interface RetestCounts {
  total: number;
  passed: number;
  failed: number;
  execution_failed: number;
  running: number;
}

export interface ReportSummary {
  assessment_status: string;
  partial: boolean;
  qa: Record<string, number>;
  security: Record<string, number>;
  evidence_total: number;
  issue_total: number;
  priority_counts: Record<string, number>;
  ai_analysis_status: string;
  correlation_status: string;
  recommendation_status: string;
  recommendation_count: number;
  retests: RetestCounts;
}

export interface ReportError {
  category: string;
  message: string;
}

export interface Report {
  id: string;
  report_id: string;
  report_number: number;
  assessment_id: string;
  target_id: string;
  target_name: string | null;
  report_version: string;
  status: ReportStatus;
  source_fingerprint: string | null;
  created_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  formats: ("html" | "pdf")[];
  source_snapshot: ReportSourceSnapshot | null;
  traceability: ReportTraceability | null;
  summary: ReportSummary | null;
  artifacts: Partial<Record<"html" | "pdf", ReportArtifact>>;
  error: ReportError | null;
  updated_at: string;
  /** POST only: unchanged source data matched an existing report. */
  reused: boolean;
}
