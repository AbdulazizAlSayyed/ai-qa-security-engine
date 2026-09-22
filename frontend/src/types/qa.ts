/** Mirrors backend/app/schemas/qa.py. Keep the two in step. */

import type { TargetType } from "@/types/target";

/**
 * passed - the check succeeded.
 * failed - the check ran and the application did not meet it.
 * error  - the check could not be executed at all (engine problem).
 */
export type QaStatus = "passed" | "failed" | "error";

export interface QaTestResult {
  name: string;
  status: QaStatus;
  duration_ms: number;
  url: string | null;
  title: string | null;
  error: string | null;
  details: Record<string, unknown>;
}

export interface QaConsoleError {
  type: string;
  message: string;
  location: string | null;
}

export interface QaNetworkFailure {
  url: string;
  method: string;
  status: number | null;
  failure: string | null;
}

export interface QaRun {
  id: string;
  target_id: string;
  target_name: string;
  target_base_url: string;
  target_type: TargetType;

  status: QaStatus;
  started_at: string;
  finished_at: string;
  duration_ms: number;

  tests: QaTestResult[];
  console_errors: QaConsoleError[];
  network_failures: QaNetworkFailure[];

  metadata: Record<string, unknown>;
  error: string | null;
}

export interface QaRunRequest {
  target_id: string;
}
