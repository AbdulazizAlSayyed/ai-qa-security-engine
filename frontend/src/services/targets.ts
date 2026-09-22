import { apiDelete, apiGet, apiPatch, apiPost } from "@/services/api";
import type {
  Target,
  TargetCreate,
  TargetDeleteResult,
  TargetUpdate,
} from "@/types/target";

const BASE = "/targets";

export function listTargets(signal?: AbortSignal): Promise<Target[]> {
  return apiGet<Target[]>(BASE, { signal });
}

export function getTarget(id: string, signal?: AbortSignal): Promise<Target> {
  return apiGet<Target>(`${BASE}/${id}`, { signal });
}

export function createTarget(body: TargetCreate): Promise<Target> {
  // The API answers 201 on a successful create.
  return apiPost<Target>(BASE, body, { acceptStatuses: [201] });
}

export function updateTarget(id: string, body: TargetUpdate): Promise<Target> {
  return apiPatch<Target>(`${BASE}/${id}`, body);
}

export function deleteTarget(id: string): Promise<TargetDeleteResult> {
  return apiDelete<TargetDeleteResult>(`${BASE}/${id}`);
}
