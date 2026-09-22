import { useState, type FormEvent } from "react";

import {
  AUTH_METHODS,
  AUTH_METHOD_LABELS,
  EMPTY_AUTHENTICATION,
  EMPTY_SECURITY_POLICY,
  ENVIRONMENTS,
  ENVIRONMENT_LABELS,
  OWNERSHIP_STATUSES,
  OWNERSHIP_STATUS_LABELS,
  TARGET_TYPES,
  TARGET_TYPE_LABELS,
  TOKEN_LOCATIONS,
  TOKEN_LOCATION_LABELS,
  type AuthMethod,
  type Environment,
  type OwnershipStatus,
  type Target,
  type TargetCreate,
  type TargetType,
  type TokenLocation,
} from "@/types/target";

interface TargetFormProps {
  /** Present when editing; absent when registering a new target. */
  target?: Target;
  onSubmit: (values: TargetCreate) => Promise<void>;
  onCancel: () => void;
}

interface FormState {
  name: string;
  base_url: string;
  api_url: string;
  type: TargetType;
  source_path: string;
  description: string;
  enabled: boolean;
  environment: Environment;
  ownership_status: OwnershipStatus;
  owned_test_environment: boolean;
  auth_enabled: boolean;
  auth_method: AuthMethod;
  login_url: string;
  username_field: string;
  password_field: string;
  cookie_name: string;
  token_location: TokenLocation;
  auth_notes: string;
  authorized_for_testing: boolean;
  allow_security_scanning: boolean;
  allow_authenticated_testing: boolean;
  allow_state_changing_requests: boolean;
}

function initialState(target?: Target): FormState {
  const auth = target?.authentication ?? EMPTY_AUTHENTICATION;
  const policy = target?.security_policy ?? EMPTY_SECURITY_POLICY;
  return {
    name: target?.name ?? "",
    base_url: target?.base_url ?? "",
    api_url: target?.api_url ?? "",
    type: target?.type ?? "web_application",
    source_path: target?.source_path ?? "",
    description: target?.description ?? "",
    enabled: target?.enabled ?? true,
    environment: target?.environment ?? "local",
    ownership_status: target?.ownership_status ?? "unknown",
    owned_test_environment: target?.owned_test_environment ?? false,
    auth_enabled: auth.enabled,
    auth_method: auth.method,
    login_url: auth.login_url ?? "",
    username_field: auth.username_field ?? "",
    password_field: auth.password_field ?? "",
    cookie_name: auth.cookie_name ?? "",
    token_location: auth.token_location,
    auth_notes: auth.notes ?? "",
    authorized_for_testing: policy.authorized_for_testing,
    allow_security_scanning: policy.allow_security_scanning,
    allow_authenticated_testing: policy.allow_authenticated_testing,
    allow_state_changing_requests: policy.allow_state_changing_requests,
  };
}

/** Blank optional text means "not set", which the API models as null. */
function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

const fieldClass =
  "w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none";
const labelClass = "block text-sm font-medium text-slate-300";
const hintClass = "mt-1 text-xs text-slate-500";
const sectionClass = "rounded-xl border border-slate-800 bg-slate-900/40 p-4";
const sectionTitleClass = "text-sm font-semibold text-slate-200";

function Checkbox({
  checked,
  onChange,
  disabled,
  children,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label
      className={`flex items-start gap-3 text-sm ${
        disabled ? "text-slate-500" : "text-slate-300"
      }`}
    >
      <input
        type="checkbox"
        className="mt-0.5 size-4 rounded border-slate-700 bg-slate-950 accent-sky-500 disabled:opacity-40"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{children}</span>
    </label>
  );
}

export default function TargetForm({ target, onSubmit, onCancel }: TargetFormProps) {
  const [values, setValues] = useState<FormState>(() => initialState(target));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  /**
   * Turning authorisation off withdraws everything it was gating, and moving
   * to production withdraws the two capabilities that environment does not
   * allow. The backend refuses those combinations either way; clearing them
   * here means the form cannot show a state the server would reject.
   */
  function setAuthorized(value: boolean) {
    setValues((current) => ({
      ...current,
      authorized_for_testing: value,
      allow_security_scanning: value && current.allow_security_scanning,
      allow_authenticated_testing: value && current.allow_authenticated_testing,
      allow_state_changing_requests: value && current.allow_state_changing_requests,
    }));
  }

  function setEnvironment(value: Environment) {
    setValues((current) => ({
      ...current,
      environment: value,
      allow_security_scanning:
        value === "production" ? false : current.allow_security_scanning,
      allow_state_changing_requests:
        value === "production" ? false : current.allow_state_changing_requests,
    }));
  }

  /** Disabling authentication also withdraws authenticated testing. */
  function setAuthEnabled(value: boolean) {
    setValues((current) => ({
      ...current,
      auth_enabled: value,
      auth_method: value
        ? current.auth_method === "none"
          ? "form_login"
          : current.auth_method
        : "none",
      allow_authenticated_testing: value && current.allow_authenticated_testing,
    }));
  }

  /**
   * Withdrawing the owned-test-environment declaration withdraws the one
   * capability it gates, so the form cannot show a state the server rejects.
   */
  function setOwnedTestEnvironment(value: boolean) {
    setValues((current) => ({
      ...current,
      owned_test_environment: value,
      allow_state_changing_requests: value && current.allow_state_changing_requests,
    }));
  }

  const isProduction = values.environment === "production";
  const isFormLogin = values.auth_enabled && values.auth_method === "form_login";
  const isCookieAuth = values.auth_enabled && values.auth_method === "cookie";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);

    try {
      await onSubmit({
        name: values.name.trim(),
        base_url: orNull(values.base_url),
        api_url: orNull(values.api_url),
        type: values.type,
        source_path: orNull(values.source_path),
        description: values.description.trim(),
        enabled: values.enabled,
        environment: values.environment,
        ownership_status: values.ownership_status,
        owned_test_environment: values.owned_test_environment,
        authentication: {
          enabled: values.auth_enabled,
          method: values.auth_enabled ? values.auth_method : "none",
          login_url: values.auth_enabled ? orNull(values.login_url) : null,
          username_field: values.auth_enabled ? orNull(values.username_field) : null,
          password_field: values.auth_enabled ? orNull(values.password_field) : null,
          cookie_name: values.auth_enabled ? orNull(values.cookie_name) : null,
          token_location: values.auth_enabled ? values.token_location : "none",
          notes: values.auth_enabled ? values.auth_notes.trim() : "",
        },
        security_policy: {
          authorized_for_testing: values.authorized_for_testing,
          allow_security_scanning: values.allow_security_scanning,
          allow_authenticated_testing: values.allow_authenticated_testing,
          allow_state_changing_requests: values.allow_state_changing_requests,
        },
      });
    } catch (caught) {
      // The backend is the source of truth on validation, so show what it said.
      setError(caught instanceof Error ? caught.message : "Could not save the target.");
      setIsSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label className={labelClass} htmlFor="target-name">
          Name <span className="text-rose-400">*</span>
        </label>
        <input
          id="target-name"
          className={`${fieldClass} mt-1`}
          value={values.name}
          onChange={(event) => set("name", event.target.value)}
          placeholder="Mini E-Commerce"
          maxLength={120}
          required
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="target-base-url">
            Base URL
          </label>
          <input
            id="target-base-url"
            className={`${fieldClass} mt-1 font-mono`}
            value={values.base_url}
            onChange={(event) => set("base_url", event.target.value)}
            placeholder="http://localhost:3000"
          />
          <p className={hintClass}>Where the UI is served.</p>
        </div>

        <div>
          <label className={labelClass} htmlFor="target-api-url">
            API URL
          </label>
          <input
            id="target-api-url"
            className={`${fieldClass} mt-1 font-mono`}
            value={values.api_url}
            onChange={(event) => set("api_url", event.target.value)}
            placeholder="http://localhost:4000"
          />
          <p className={hintClass}>Where the API is served.</p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="target-type">
            Type
          </label>
          <select
            id="target-type"
            className={`${fieldClass} mt-1`}
            value={values.type}
            onChange={(event) => set("type", event.target.value as TargetType)}
          >
            {TARGET_TYPES.map((type) => (
              <option key={type} value={type}>
                {TARGET_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelClass} htmlFor="target-source-path">
            Source path
          </label>
          <input
            id="target-source-path"
            className={`${fieldClass} mt-1 font-mono`}
            value={values.source_path}
            onChange={(event) => set("source_path", event.target.value)}
            placeholder="optional"
          />
          <p className={hintClass}>Only needed for static analysis later.</p>
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="target-description">
          Description
        </label>
        <textarea
          id="target-description"
          className={`${fieldClass} mt-1 min-h-20 resize-y`}
          value={values.description}
          onChange={(event) => set("description", event.target.value)}
          maxLength={2000}
          placeholder="What this application is and why it is registered."
        />
      </div>

      <label className="flex items-center gap-3 text-sm text-slate-300">
        <input
          type="checkbox"
          className="size-4 rounded border-slate-700 bg-slate-950 accent-sky-500"
          checked={values.enabled}
          onChange={(event) => set("enabled", event.target.checked)}
        />
        Enabled &mdash; assessments may run against this target
      </label>

      <section className={sectionClass}>
        <h3 className={sectionTitleClass}>Environment &amp; ownership</h3>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass} htmlFor="target-environment">
              Environment
            </label>
            <select
              id="target-environment"
              className={`${fieldClass} mt-1`}
              value={values.environment}
              onChange={(event) => setEnvironment(event.target.value as Environment)}
            >
              {ENVIRONMENTS.map((value) => (
                <option key={value} value={value}>
                  {ENVIRONMENT_LABELS[value]}
                </option>
              ))}
            </select>
            {isProduction ? (
              <p className="mt-1 text-xs text-amber-300/90">
                Production targets cannot be scanned or written to.
              </p>
            ) : null}
          </div>

          <div>
            <label className={labelClass} htmlFor="target-ownership">
              Ownership
            </label>
            <select
              id="target-ownership"
              className={`${fieldClass} mt-1`}
              value={values.ownership_status}
              onChange={(event) =>
                set("ownership_status", event.target.value as OwnershipStatus)
              }
            >
              {OWNERSHIP_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {OWNERSHIP_STATUS_LABELS[value]}
                </option>
              ))}
            </select>
            <p className={hintClass}>How this platform comes to be pointed at it.</p>
          </div>
        </div>

        <div className="mt-4 border-t border-slate-800 pt-4">
          <Checkbox
            checked={values.owned_test_environment}
            onChange={setOwnedTestEnvironment}
          >
            <span className="font-medium text-slate-200">Owned test environment</span>
            <span className="block text-xs text-slate-500">
              I declare this application is my own test environment. Required before a
              later phase may send state-changing requests. It enables nothing today.
            </span>
          </Checkbox>
        </div>
      </section>

      <section className={sectionClass}>
        <h3 className={sectionTitleClass}>Authentication</h3>
        <p className="mt-1 text-xs text-slate-500">
          Describes how this target authenticates. Nothing here logs in yet, and no
          password is ever stored &mdash; identities live under Test accounts.
        </p>

        <div className="mt-3 flex flex-col gap-3">
          <Checkbox checked={values.auth_enabled} onChange={setAuthEnabled}>
            This target has authentication
          </Checkbox>

          {values.auth_enabled ? (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className={labelClass} htmlFor="target-auth-method">
                    Method
                  </label>
                  <select
                    id="target-auth-method"
                    className={`${fieldClass} mt-1`}
                    value={values.auth_method}
                    onChange={(event) =>
                      set("auth_method", event.target.value as AuthMethod)
                    }
                  >
                    {AUTH_METHODS.filter((method) => method !== "none").map((method) => (
                      <option key={method} value={method}>
                        {AUTH_METHOD_LABELS[method]}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className={labelClass} htmlFor="target-token-location">
                    Credential kept in
                  </label>
                  <select
                    id="target-token-location"
                    className={`${fieldClass} mt-1`}
                    value={values.token_location}
                    onChange={(event) =>
                      set("token_location", event.target.value as TokenLocation)
                    }
                  >
                    {TOKEN_LOCATIONS.map((value) => (
                      <option key={value} value={value}>
                        {TOKEN_LOCATION_LABELS[value]}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className={labelClass} htmlFor="target-login-url">
                  Login URL {isFormLogin ? <span className="text-rose-400">*</span> : null}
                </label>
                <input
                  id="target-login-url"
                  className={`${fieldClass} mt-1 font-mono`}
                  value={values.login_url}
                  onChange={(event) => set("login_url", event.target.value)}
                  placeholder="http://localhost:3000/login"
                />
              </div>

              {isCookieAuth ? (
                <div>
                  <label className={labelClass} htmlFor="target-cookie-name">
                    Cookie name <span className="text-rose-400">*</span>
                  </label>
                  <input
                    id="target-cookie-name"
                    className={`${fieldClass} mt-1 font-mono`}
                    value={values.cookie_name}
                    onChange={(event) => set("cookie_name", event.target.value)}
                    placeholder="session"
                  />
                  <p className={hintClass}>
                    The cookie's name &mdash; never its value.
                  </p>
                </div>
              ) : null}

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className={labelClass} htmlFor="target-username-field">
                    Username field{" "}
                    {isFormLogin ? <span className="text-rose-400">*</span> : null}
                  </label>
                  <input
                    id="target-username-field"
                    className={`${fieldClass} mt-1 font-mono`}
                    value={values.username_field}
                    onChange={(event) => set("username_field", event.target.value)}
                    placeholder="login-email"
                  />
                  <p className={hintClass}>The input's name or test id.</p>
                </div>

                <div>
                  <label className={labelClass} htmlFor="target-password-field">
                    Password field{" "}
                    {isFormLogin ? <span className="text-rose-400">*</span> : null}
                  </label>
                  <input
                    id="target-password-field"
                    className={`${fieldClass} mt-1 font-mono`}
                    value={values.password_field}
                    onChange={(event) => set("password_field", event.target.value)}
                    placeholder="login-password"
                  />
                  <p className={hintClass}>
                    The input's name or test id &mdash; never a password.
                  </p>
                </div>
              </div>

              <div>
                <label className={labelClass} htmlFor="target-auth-notes">
                  Notes
                </label>
                <textarea
                  id="target-auth-notes"
                  className={`${fieldClass} mt-1 min-h-16 resize-y`}
                  value={values.auth_notes}
                  onChange={(event) => set("auth_notes", event.target.value)}
                  maxLength={1000}
                  placeholder="Anything a later phase would need to know about signing in."
                />
                <p className={hintClass}>Never put a credential here.</p>
              </div>
            </>
          ) : null}
        </div>
      </section>

      <section className={sectionClass}>
        <h3 className={sectionTitleClass}>Security testing policy</h3>
        <p className="mt-1 text-xs text-slate-500">
          Everything is off until it is turned on deliberately. Authorisation gates the
          rest.
        </p>

        <div className="mt-3 flex flex-col gap-3">
          <Checkbox
            checked={values.authorized_for_testing}
            onChange={setAuthorized}
          >
            <span className="font-medium text-slate-200">
              Authorized for testing
            </span>
            <span className="block text-xs text-slate-500">
              This platform is permitted to test this application.
            </span>
          </Checkbox>

          <div className="ml-7 flex flex-col gap-3 border-l border-slate-800 pl-4">
            <Checkbox
              checked={values.allow_security_scanning}
              disabled={!values.authorized_for_testing || isProduction}
              onChange={(value) => set("allow_security_scanning", value)}
            >
              Allow security scanning
              {isProduction ? (
                <span className="block text-xs text-amber-300/80">
                  Not available for production.
                </span>
              ) : null}
            </Checkbox>

            <Checkbox
              checked={values.allow_authenticated_testing}
              disabled={!values.authorized_for_testing || !values.auth_enabled}
              onChange={(value) => set("allow_authenticated_testing", value)}
            >
              Allow authenticated testing
              {!values.auth_enabled ? (
                <span className="block text-xs text-slate-500">
                  Needs authentication configured above.
                </span>
              ) : null}
            </Checkbox>

            <Checkbox
              checked={values.allow_state_changing_requests}
              disabled={
                !values.authorized_for_testing ||
                isProduction ||
                !values.owned_test_environment
              }
              onChange={(value) => set("allow_state_changing_requests", value)}
            >
              Allow state-changing requests
              {isProduction ? (
                <span className="block text-xs text-amber-300/80">
                  Not available for production.
                </span>
              ) : !values.owned_test_environment ? (
                <span className="block text-xs text-slate-500">
                  Needs the owned-test-environment declaration above.
                </span>
              ) : null}
            </Checkbox>
          </div>
        </div>
      </section>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
        >
          {error}
        </p>
      ) : null}

      <div className="flex justify-end gap-2 border-t border-slate-800 pt-4">
        <button
          type="button"
          onClick={onCancel}
          disabled={isSaving}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSaving}
          className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSaving ? "Saving..." : target ? "Save changes" : "Register target"}
        </button>
      </div>
    </form>
  );
}
