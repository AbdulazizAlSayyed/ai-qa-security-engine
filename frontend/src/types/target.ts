/** Mirrors backend/app/schemas/target.py. Keep the two in step. */

export const TARGET_TYPES = ["web_application", "api", "web_and_api"] as const;

export type TargetType = (typeof TARGET_TYPES)[number];

export const TARGET_TYPE_LABELS: Record<TargetType, string> = {
  web_application: "Web application",
  api: "API",
  web_and_api: "Web + API",
};

export interface Target {
  id: string;
  name: string;
  base_url: string | null;
  api_url: string | null;
  type: TargetType;
  source_path: string | null;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** Body for POST /targets. */
export interface TargetCreate {
  name: string;
  base_url: string | null;
  api_url: string | null;
  type: TargetType;
  source_path: string | null;
  description: string;
  enabled: boolean;
}

/** Body for PATCH /targets/{id}. Omitted keys are left untouched. */
export type TargetUpdate = Partial<TargetCreate>;

export interface TargetDeleteResult {
  deleted: boolean;
  id: string;
}
