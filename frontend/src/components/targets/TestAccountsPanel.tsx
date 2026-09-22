import { useCallback, useEffect, useState, type FormEvent } from "react";

import StatusPill from "@/components/StatusPill";
import {
  createTestAccount,
  deleteTestAccount,
  listTestAccounts,
  updateTestAccount,
} from "@/services/testAccounts";
import {
  ACCOUNT_ROLES,
  ACCOUNT_ROLE_LABELS,
  PURPOSE_SUGGESTIONS,
  type AccountRole,
  type TestAccount,
  type TestAccountCreate,
} from "@/types/testAccount";
import type { Target } from "@/types/target";

interface TestAccountsPanelProps {
  target: Target;
}

const fieldClass =
  "w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none";
const labelClass = "block text-sm font-medium text-slate-300";
const hintClass = "mt-1 text-xs text-slate-500";

function emptyForm(): TestAccountCreate {
  return {
    name: "",
    role: "user",
    purpose: "",
    username: null,
    credential_reference: null,
    description: "",
    enabled: true,
  };
}

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Manage the identities registered for one target.
 *
 * No password is entered, displayed or transmitted here, and there is no
 * field that could hold one. An account names an environment variable; the
 * operator sets that variable on the machine running the backend, and the
 * panel only reports whether it is currently set.
 */
export default function TestAccountsPanel({ target }: TestAccountsPanelProps) {
  const [accounts, setAccounts] = useState<TestAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [values, setValues] = useState<TestAccountCreate>(emptyForm);

  const [username, setUsername] = useState("");
  const [credentialReference, setCredentialReference] = useState("");

  const refresh = useCallback(async () => {
    try {
      setAccounts(await listTestAccounts(target.id));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load accounts.");
    }
  }, [target.id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function resetForm() {
    setValues(emptyForm());
    setUsername("");
    setCredentialReference("");
    setFormError(null);
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setFormError(null);
    try {
      await createTestAccount(target.id, {
        ...values,
        name: values.name.trim(),
        username: orNull(username),
        credential_reference: orNull(credentialReference),
      });
      resetForm();
      setShowForm(false);
      await refresh();
    } catch (caught) {
      // The backend owns validation, so show exactly what it objected to.
      setFormError(
        caught instanceof Error ? caught.message : "Could not create the account.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  async function toggleEnabled(account: TestAccount) {
    setError(null);
    try {
      await updateTestAccount(target.id, account.id, { enabled: !account.enabled });
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update the account.");
    }
  }

  async function remove(account: TestAccount) {
    setError(null);
    try {
      await deleteTestAccount(target.id, account.id);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete the account.");
    }
  }

  const isAnonymous = values.role === "anonymous";

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-slate-400">
        Identities a later phase may use against{" "}
        <span className="text-slate-200">{target.name}</span>. They are configuration
        only &mdash; nothing signs in yet.
      </p>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
        >
          {error}
        </p>
      ) : null}

      {accounts === null ? (
        <p className="text-sm text-slate-500">Loading accounts...</p>
      ) : accounts.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-6 text-center text-sm text-slate-400">
          No test accounts yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {accounts.map((account) => (
            <li
              key={account.id}
              className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-100">{account.name}</span>
                    <StatusPill tone="neutral">
                      {ACCOUNT_ROLE_LABELS[account.role]}
                    </StatusPill>
                    <StatusPill tone={account.enabled ? "positive" : "neutral"}>
                      {account.enabled ? "Enabled" : "Disabled"}
                    </StatusPill>
                  </div>

                  <dl className="mt-2 flex flex-col gap-1 text-xs">
                    <div className="flex gap-2">
                      <dt className="text-slate-500">Username</dt>
                      <dd className="font-mono break-all text-slate-300">
                        {account.username ?? "none"}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="text-slate-500">Password env var</dt>
                      <dd className="font-mono break-all text-slate-300">
                        {account.credential_reference ?? "none"}
                        {account.credential_reference ? (
                          <span
                            className={
                              account.credential_available
                                ? "ml-2 text-emerald-300"
                                : "ml-2 text-amber-300"
                            }
                          >
                            {account.credential_available ? "set" : "not set on server"}
                          </span>
                        ) : null}
                      </dd>
                    </div>
                    {account.purpose ? (
                      <div className="flex gap-2">
                        <dt className="text-slate-500">Purpose</dt>
                        <dd className="text-slate-300">{account.purpose}</dd>
                      </div>
                    ) : null}
                  </dl>
                </div>

                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void toggleEnabled(account)}
                    className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
                  >
                    {account.enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(account)}
                    className="rounded-lg border border-rose-500/40 px-3 py-1.5 text-xs text-rose-200 transition-colors hover:bg-rose-500/10"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {showForm ? (
        <form
          onSubmit={handleCreate}
          className="flex flex-col gap-4 rounded-xl border border-slate-800 bg-slate-900/40 p-4"
        >
          <div>
            <label className={labelClass} htmlFor="account-name">
              Name <span className="text-rose-400">*</span>
            </label>
            <input
              id="account-name"
              className={`${fieldClass} mt-1`}
              value={values.name}
              onChange={(event) => setValues({ ...values, name: event.target.value })}
              placeholder="Admin test account"
              maxLength={120}
              required
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelClass} htmlFor="account-role">
                Role
              </label>
              <select
                id="account-role"
                className={`${fieldClass} mt-1`}
                value={values.role}
                onChange={(event) =>
                  setValues({ ...values, role: event.target.value as AccountRole })
                }
              >
                {ACCOUNT_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {ACCOUNT_ROLE_LABELS[role]}
                  </option>
                ))}
              </select>
              <p className={hintClass}>Metadata. Nothing is granted by it.</p>
            </div>

            <div>
              <label className={labelClass} htmlFor="account-purpose">
                Purpose
              </label>
              <input
                id="account-purpose"
                list="account-purpose-suggestions"
                className={`${fieldClass} mt-1`}
                value={values.purpose}
                onChange={(event) =>
                  setValues({ ...values, purpose: event.target.value })
                }
                placeholder="authorization_test_user"
                maxLength={120}
              />
              <datalist id="account-purpose-suggestions">
                {PURPOSE_SUGGESTIONS.map((suggestion) => (
                  <option key={suggestion} value={suggestion} />
                ))}
              </datalist>
            </div>
          </div>

          {isAnonymous ? (
            <p className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2 text-xs text-slate-400">
              An anonymous account represents an unauthenticated visitor, so it carries
              no username and no credential.
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className={labelClass} htmlFor="account-username">
                  Username
                </label>
                <input
                  id="account-username"
                  className={`${fieldClass} mt-1 font-mono`}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="admin@test.local"
                  maxLength={200}
                />
              </div>

              <div>
                <label className={labelClass} htmlFor="account-credential-reference">
                  Password environment variable
                </label>
                <input
                  id="account-credential-reference"
                  className={`${fieldClass} mt-1 font-mono`}
                  value={credentialReference}
                  onChange={(event) => setCredentialReference(event.target.value)}
                  placeholder="E2E_ADMIN_PASSWORD"
                  maxLength={100}
                />
                <p className="mt-1 text-xs text-amber-300/80">
                  The variable's NAME, not the password. Set its value in the backend's
                  environment; it is never sent here or stored.
                </p>
              </div>
            </div>
          )}

          {formError ? (
            <p
              role="alert"
              className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
            >
              {formError}
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                resetForm();
                setShowForm(false);
              }}
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
              {isSaving ? "Saving..." : "Add account"}
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="self-start rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400"
        >
          Add test account
        </button>
      )}
    </div>
  );
}
