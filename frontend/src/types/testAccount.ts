/**
 * Mirrors backend/app/schemas/test_account.py. Keep the two in step.
 *
 * There is no password field anywhere in this file, and there should never
 * be one. `credential_reference` is the NAME of an environment variable set
 * on the machine running the backend; the value behind it never reaches the
 * API, the browser, or MongoDB.
 */

/**
 * Suggestions offered in the UI, not a constraint. A role is whatever the
 * target's own application calls it, so the backend accepts any label and
 * nothing here matches on the list.
 */
export const ROLE_SUGGESTIONS = [
  "admin",
  "user",
  "manager",
  "customer",
  "readonly",
  "guest",
  "anonymous",
] as const;

/** Free text, validated as a label by the backend. */
export type AccountRole = string;

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

/**
 * Environment variable NAMES. Never values — the browser is never given a
 * place to hold one, and the API never sends one.
 */
export interface CredentialReference {
  username_env: string | null;
  password_env: string | null;
}

export const EMPTY_CREDENTIAL_REFERENCE: CredentialReference = {
  username_env: null,
  password_env: null,
};

export interface TestAccount {
  id: string;
  target_id: string;
  name: string;
  role: AccountRole;
  purpose: string;
  username: string | null;
  credential_reference: CredentialReference;
  /** Whether every named env var is currently set on the server. Never a value. */
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
  credential_reference: CredentialReference;
  description: string;
  enabled: boolean;
}

/** Body for PATCH. Omitted keys are left untouched. */
export type TestAccountUpdate = Partial<TestAccountCreate>;

export interface TestAccountDeleteResult {
  deleted: boolean;
  id: string;
}
