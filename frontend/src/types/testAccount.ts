/**
 * Mirrors backend/app/schemas/test_account.py. Keep the two in step.
 *
 * There is no password field anywhere in this file, and there should never
 * be one. `credential_reference` is the NAME of an environment variable set
 * on the machine running the backend; the value behind it never reaches the
 * API, the browser, or MongoDB.
 */

export const ACCOUNT_ROLES = [
  "admin",
  "user",
  "readonly",
  "anonymous",
  "custom",
] as const;

export type AccountRole = (typeof ACCOUNT_ROLES)[number];

export const ACCOUNT_ROLE_LABELS: Record<AccountRole, string> = {
  admin: "Admin",
  user: "User",
  readonly: "Read-only",
  anonymous: "Anonymous",
  custom: "Custom",
};

/**
 * Suggestions for the purpose field, offered in the UI as a datalist. The
 * backend stores whatever string it is given: these are conveniences for
 * the operator, never a vocabulary any engine matches on.
 */
export const PURPOSE_SUGGESTIONS = [
  "primary_test_user",
  "admin_test_user",
  "readonly_test_user",
  "authorization_test_user",
] as const;

export interface TestAccount {
  id: string;
  target_id: string;
  name: string;
  role: AccountRole;
  purpose: string;
  username: string | null;
  /** The env var's name, never its value. */
  credential_reference: string | null;
  /** Whether that env var is currently set on the server. Never the value. */
  credential_available: boolean;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** Body for POST /targets/{target_id}/test-accounts. */
export interface TestAccountCreate {
  name: string;
  role: AccountRole;
  purpose: string;
  username: string | null;
  credential_reference: string | null;
  description: string;
  enabled: boolean;
}

/** Body for PATCH. Omitted keys are left untouched. */
export type TestAccountUpdate = Partial<TestAccountCreate>;

export interface TestAccountDeleteResult {
  deleted: boolean;
  id: string;
}
