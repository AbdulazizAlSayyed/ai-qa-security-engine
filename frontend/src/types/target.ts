/** Mirrors backend/app/schemas/target.py. Keep the two in step. */

export const TARGET_TYPES = ["web_application", "api", "web_and_api"] as const;

export type TargetType = (typeof TARGET_TYPES)[number];

export const TARGET_TYPE_LABELS: Record<TargetType, string> = {
  web_application: "Web application",
  api: "API",
  web_and_api: "Web + API",
};

export const ENVIRONMENTS = [
  "local",
  "development",
  "staging",
  "test",
  "production",
] as const;

export type Environment = (typeof ENVIRONMENTS)[number];

export const ENVIRONMENT_LABELS: Record<Environment, string> = {
  local: "Local",
  development: "Development",
  staging: "Staging",
  test: "Test",
  production: "Production",
};

export const OWNERSHIP_STATUSES = [
  "owned",
  "authorized",
  "third_party",
  "unknown",
] as const;

export type OwnershipStatus = (typeof OWNERSHIP_STATUSES)[number];

export const OWNERSHIP_STATUS_LABELS: Record<OwnershipStatus, string> = {
  owned: "Owned by us",
  authorized: "Authorized in writing",
  third_party: "Third party",
  unknown: "Not recorded",
};

export const AUTH_METHODS = [
  "none",
  "form",
  "basic",
  "bearer",
  "cookie",
  "custom",
] as const;

export type AuthMethod = (typeof AUTH_METHODS)[number];

export const AUTH_METHOD_LABELS: Record<AuthMethod, string> = {
  none: "None",
  form: "Login form",
  basic: "HTTP Basic",
  bearer: "Bearer token",
  cookie: "Session cookie",
  custom: "Custom",
};

export const TOKEN_LOCATIONS = [
  "none",
  "header",
  "cookie",
  "local_storage",
  "session_storage",
] as const;

export type TokenLocation = (typeof TOKEN_LOCATIONS)[number];

export const TOKEN_LOCATION_LABELS: Record<TokenLocation, string> = {
  none: "Not applicable",
  header: "Authorization header",
  cookie: "Cookie",
  local_storage: "localStorage",
  session_storage: "sessionStorage",
};

/**
 * How the target authenticates. Configuration only — the platform does not
 * log in yet, and no credential is ever held here. The field names describe
 * the login form; the identities live on test accounts.
 */
export interface AuthenticationProfile {
  enabled: boolean;
  method: AuthMethod;
  login_url: string | null;
  username_field: string | null;
  password_field: string | null;
  token_location: TokenLocation;
}

/**
 * What this platform is permitted to do to the target. Everything defaults
 * to false, and `authorized_for_testing` gates the rest: the backend rejects
 * any capability enabled without it.
 */
export interface SecurityPolicy {
  authorized_for_testing: boolean;
  allow_security_scanning: boolean;
  allow_authenticated_testing: boolean;
  allow_state_changing_requests: boolean;
}

export interface Target {
  id: string;
  name: string;
  base_url: string | null;
  api_url: string | null;
  type: TargetType;
  source_path: string | null;
  description: string;
  enabled: boolean;
  environment: Environment;
  ownership_status: OwnershipStatus;
  authentication: AuthenticationProfile;
  security_policy: SecurityPolicy;
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
  environment: Environment;
  ownership_status: OwnershipStatus;
  authentication: AuthenticationProfile;
  security_policy: SecurityPolicy;
}

/** Body for PATCH /targets/{id}. Omitted keys are left untouched. */
export type TargetUpdate = Partial<TargetCreate>;

export interface TargetDeleteResult {
  deleted: boolean;
  id: string;
}

export const EMPTY_AUTHENTICATION: AuthenticationProfile = {
  enabled: false,
  method: "none",
  login_url: null,
  username_field: null,
  password_field: null,
  token_location: "none",
};

export const EMPTY_SECURITY_POLICY: SecurityPolicy = {
  authorized_for_testing: false,
  allow_security_scanning: false,
  allow_authenticated_testing: false,
  allow_state_changing_requests: false,
};
