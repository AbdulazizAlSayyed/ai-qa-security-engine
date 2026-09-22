/** Mirrors backend/app/schemas/security.py. Keep the two in step. */

import type { TargetType } from "@/types/target";

export const SEVERITIES = ["high", "medium", "low", "informational"] as const;
export type Severity = (typeof SEVERITIES)[number];

/**
 * completed - the scanner ran to the end.
 * skipped   - legitimately not applicable (disabled, no API URL, no credentials).
 * failed    - asked to run and could not finish.
 */
export type ComponentStatus = "completed" | "skipped" | "failed";

/** error means the platform broke, not that the target is vulnerable. */
export type SecurityRunStatus = "completed" | "failed" | "error";

export interface SecurityFinding {
  id: string;
  source: string;
  rule_id: string | null;
  name: string;
  description: string | null;
  severity: Severity;
  confidence: string | null;
  url: string | null;
  method: string | null;
  parameter: string | null;
  evidence: string | null;
  solution: string | null;
  reference: string | null;
  cwe: string | null;
  wasc: string | null;
  raw: Record<string, unknown>;
}

export interface SecurityComponent {
  name: string;
  status: ComponentStatus;
  enabled: boolean;
  duration_ms: number;
  detail: string | null;
  findings: SecurityFinding[];
  metadata: Record<string, unknown>;
}

export interface SecuritySummary {
  total_findings: number;
  high: number;
  medium: number;
  low: number;
  informational: number;
}

export interface SecurityRun {
  id: string;
  target_id: string;
  target_name: string;
  target_base_url: string;
  target_api_url: string | null;
  target_type: TargetType;

  status: SecurityRunStatus;
  started_at: string;
  finished_at: string;
  duration_ms: number;

  components: SecurityComponent[];
  findings: SecurityFinding[];
  summary: SecuritySummary;

  engine_metadata: Record<string, unknown>;
  error: string | null;
}
