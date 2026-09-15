/** Mirrors backend/app/schemas/health.py. Keep the two in step. */

export type DatabaseStatus = "connected" | "unavailable";
export type ServiceStatus = "ok" | "degraded";

export interface DatabaseHealth {
  status: DatabaseStatus;
  database: string;
  latency_ms: number | null;
  server_version: string | null;
  error: string | null;
}

export interface HealthResponse {
  status: ServiceStatus;
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  database: DatabaseHealth;
}
