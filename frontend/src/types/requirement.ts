/**
 * Mirrors backend/app/schemas/requirement.py. Keep the two in step -
 * tests/test_frontend_contract.py fails when they drift.
 *
 * A requirement is a statement about what a target is supposed to do. It
 * holds no secret and has no field one could go in, which is why the
 * credential check in the contract test covers this file too.
 */

/** Where the statement came from. Provenance, not permission. */
export const REQUIREMENT_SOURCES = ["manual", "user_story", "brd", "openapi"] as const;
export type RequirementSource = (typeof REQUIREMENT_SOURCES)[number];

export const SOURCE_LABELS: Record<RequirementSource, string> = {
  manual: "Written by hand",
  user_story: "User story",
  brd: "From a business document",
  openapi: "From an OpenAPI document",
};

/** Whether the statement is agreed. New requirements start as drafts. */
export const REQUIREMENT_STATUSES = ["draft", "approved", "deprecated"] as const;
export type RequirementStatus = (typeof REQUIREMENT_STATUSES)[number];

export const STATUS_LABELS: Record<RequirementStatus, string> = {
  draft: "Draft",
  approved: "Approved",
  deprecated: "Deprecated",
};

/**
 * How important the requirement is. A separate vocabulary from issue
 * priority (P1..P4) and tool severity on purpose: how badly a feature is
 * wanted is a different question from how bad a defect is.
 */
export const REQUIREMENT_PRIORITIES = ["low", "medium", "high", "critical"] as const;
export type RequirementPriority = (typeof REQUIREMENT_PRIORITIES)[number];

export const PRIORITY_LABELS: Record<RequirementPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

/** What kind of expectation this is - not which feature it belongs to. */
export const REQUIREMENT_AREAS = [
  "functional",
  "authentication",
  "authorization",
  "security",
  "usability",
  "performance",
  "data",
  "api",
  "ui",
] as const;
export type RequirementArea = (typeof REQUIREMENT_AREAS)[number];

export const AREA_LABELS: Record<RequirementArea, string> = {
  functional: "Functional",
  authentication: "Authentication",
  authorization: "Authorization",
  security: "Security",
  usability: "Usability",
  performance: "Performance",
  data: "Data",
  api: "API",
  ui: "UI",
};

/**
 * One checkable statement belonging to one requirement.
 *
 * `id` is allocated by the backend and is stable for the life of the
 * criterion. Send it back to keep that criterion; send `null` to ask for a
 * new one; leave it out of the array entirely to delete it.
 */
export interface AcceptanceCriterion {
  id: string | null;
  text: string;
}

export interface Requirement {
  id: string;
  target_id: string;
  key: string;
  key_number: number;
  title: string;
  description: string;
  source: RequirementSource;
  source_reference: string;
  acceptance_criteria: AcceptanceCriterion[];
  area: RequirementArea;
  priority: RequirementPriority;
  status: RequirementStatus;
  extraction_id: string;
  created_at: string;
  updated_at: string;
}

/** Body for POST /targets/{target_id}/requirements. The key is not ours to pick. */
export interface RequirementCreate {
  title: string;
  description: string;
  source: RequirementSource;
  source_reference: string;
  acceptance_criteria: AcceptanceCriterion[];
  area: RequirementArea;
  priority: RequirementPriority;
  status: RequirementStatus;
}

/** Body for PATCH. Omitted keys are left untouched. */
export type RequirementUpdate = Partial<RequirementCreate>;

export interface RequirementDeleteResult {
  deleted: boolean;
  id: string;
  key: string;
}

/**
 * A proposal, not a requirement. It has no key, no id and no row in the
 * database, and it becomes a requirement only when a person sends it back
 * through the import endpoint.
 */
export interface RequirementCandidate {
  title: string;
  description: string;
  source_reference: string;
  acceptance_criteria: string[];
  area: RequirementArea;
  priority: RequirementPriority;
  note: string;
}

export interface RequirementExtraction {
  target_id: string;
  source: RequirementSource;
  extraction_id: string;
  provider: string;
  model: string;
  candidates: RequirementCandidate[];
  notes: string[];
  document_chars: number;
}

export interface RequirementImportResult {
  created: Requirement[];
  count: number;
}

/** Filters accepted by GET /targets/{target_id}/requirements. */
export interface RequirementFilters {
  status?: RequirementStatus;
  priority?: RequirementPriority;
  area?: RequirementArea;
  source?: RequirementSource;
}

/** The shape the registry form starts from. */
export const EMPTY_REQUIREMENT: RequirementCreate = {
  title: "",
  description: "",
  source: "manual",
  source_reference: "",
  acceptance_criteria: [],
  area: "functional",
  priority: "medium",
  status: "draft",
};

/**
 * Turn a reviewed candidate into a create payload.
 *
 * Criteria arrive as plain strings and leave with `id: null`, because a
 * candidate has no identity yet - the backend allocates AC-001 onwards when
 * the requirement is actually written.
 */
export function candidateToCreate(
  candidate: RequirementCandidate,
  source: RequirementSource,
): RequirementCreate {
  return {
    title: candidate.title,
    description: candidate.description,
    source,
    source_reference: candidate.source_reference,
    acceptance_criteria: candidate.acceptance_criteria.map((text) => ({ id: null, text })),
    area: candidate.area,
    priority: candidate.priority,
    status: "draft",
  };
}
