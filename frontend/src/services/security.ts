import { apiGet, apiPost } from "@/services/api";
import type { SecurityRun } from "@/types/security";

const BASE = "/security/runs";

export function listSecurityRuns(limit = 50, signal?: AbortSignal): Promise<SecurityRun[]> {
  return apiGet<SecurityRun[]>(`${BASE}?limit=${limit}`, { signal });
}

export function getSecurityRun(id: string, signal?: AbortSignal): Promise<SecurityRun> {
  return apiGet<SecurityRun>(`${BASE}/${id}`, { signal });
}

/**
 * Start a security assessment.
 *
 * Only a registered target id is sent - never a URL. The backend reads the
 * URLs from the registry, so the platform can only scan what someone
 * deliberately registered.
 *
 * Resolves once the scanners have finished, which takes seconds. A run that
 * reports findings still resolves successfully.
 */
export function startSecurityRun(targetId: string): Promise<SecurityRun> {
  return apiPost<SecurityRun>(BASE, { target_id: targetId }, { acceptStatuses: [201] });
}
