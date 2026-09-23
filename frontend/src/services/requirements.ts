import { apiDelete, apiGet, apiPatch, apiPost } from "@/services/api";
import type {
  Requirement,
  RequirementCreate,
  RequirementDeleteResult,
  RequirementExtraction,
  RequirementFilters,
  RequirementImportResult,
  RequirementUpdate,
} from "@/types/requirement";

/**
 * Requirements are always addressed through their target. There is no route
 * that reaches one without naming the target it belongs to, which is what
 * keeps one application's requirements out of another's registry.
 */
const base = (targetId: string) => `/targets/${targetId}/requirements`;

function query(filters: RequirementFilters = {}): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.priority) params.set("priority", filters.priority);
  if (filters.area) params.set("area", filters.area);
  if (filters.source) params.set("source", filters.source);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function listRequirements(
  targetId: string,
  filters: RequirementFilters = {},
  signal?: AbortSignal,
): Promise<Requirement[]> {
  return apiGet<Requirement[]>(`${base(targetId)}${query(filters)}`, { signal });
}

export function getRequirement(
  targetId: string,
  requirementId: string,
  signal?: AbortSignal,
): Promise<Requirement> {
  return apiGet<Requirement>(`${base(targetId)}/${requirementId}`, { signal });
}

export function createRequirement(
  targetId: string,
  body: RequirementCreate,
): Promise<Requirement> {
  // The API answers 201 on a successful create.
  return apiPost<Requirement>(base(targetId), body, { acceptStatuses: [201] });
}

export function updateRequirement(
  targetId: string,
  requirementId: string,
  body: RequirementUpdate,
): Promise<Requirement> {
  return apiPatch<Requirement>(`${base(targetId)}/${requirementId}`, body);
}

export function deleteRequirement(
  targetId: string,
  requirementId: string,
): Promise<RequirementDeleteResult> {
  return apiDelete<RequirementDeleteResult>(`${base(targetId)}/${requirementId}`);
}

/**
 * Ask the configured AI provider to read a business document.
 *
 * Nothing is stored by this call. What comes back are candidates for a
 * person to read, edit and either accept or drop; only `importRequirements`
 * below writes anything.
 */
export function extractFromBrd(
  targetId: string,
  document: string,
): Promise<RequirementExtraction> {
  return apiPost<RequirementExtraction>(`${base(targetId)}/extract-from-brd`, {
    document,
  });
}

/**
 * Parse an OpenAPI document into candidates, offline.
 *
 * The API the document describes is never contacted - this is a read of the
 * text that was pasted in, nothing more.
 */
export function extractFromOpenApi(
  targetId: string,
  document: string,
): Promise<RequirementExtraction> {
  return apiPost<RequirementExtraction>(`${base(targetId)}/extract-from-openapi`, {
    document,
  });
}

/**
 * Write the candidates a person accepted.
 *
 * This is the approval step. Whatever is in `requirements` is what gets
 * stored, edits included; whatever the reviewer rejected is simply not here.
 */
export function importRequirements(
  targetId: string,
  requirements: RequirementCreate[],
  extractionId = "",
): Promise<RequirementImportResult> {
  return apiPost<RequirementImportResult>(
    `${base(targetId)}/import`,
    { requirements, extraction_id: extractionId },
    { acceptStatuses: [201] },
  );
}
