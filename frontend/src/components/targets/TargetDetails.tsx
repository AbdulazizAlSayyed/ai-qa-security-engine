import type { ReactNode } from "react";

import StatusPill from "@/components/StatusPill";
import {
  AUTH_METHOD_LABELS,
  ENVIRONMENT_LABELS,
  OWNERSHIP_STATUS_LABELS,
  TARGET_TYPE_LABELS,
  TOKEN_LOCATION_LABELS,
  type Target,
} from "@/types/target";

interface TargetDetailsProps {
  target: Target;
  onClose: () => void;
  onEdit: (target: Target) => void;
  onManageAccounts: (target: Target) => void;
}

/** One capability of the security policy, shown as granted or withheld. */
function Capability({ label, granted }: { label: string; granted: boolean }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <span
        aria-hidden
        className={`inline-block size-1.5 rounded-full ${
          granted ? "bg-amber-400" : "bg-slate-700"
        }`}
      />
      <span className={granted ? "text-slate-200" : "text-slate-500"}>{label}</span>
      <span className={granted ? "text-amber-300/80" : "text-slate-600"}>
        {granted ? "allowed" : "not allowed"}
      </span>
    </li>
  );
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-slate-800/70 py-3 last:border-b-0 sm:grid-cols-3 sm:gap-4">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="min-w-0 sm:col-span-2">{children}</dd>
    </div>
  );
}

function Link({ value }: { value: string | null }) {
  if (!value) return <span className="font-mono text-sm text-slate-600">not set</span>;
  return (
    <a
      href={value}
      target="_blank"
      rel="noreferrer noopener"
      className="font-mono text-sm break-all text-sky-300 hover:text-sky-200 hover:underline"
    >
      {value}
    </a>
  );
}

export default function TargetDetails({
  target,
  onClose,
  onEdit,
  onManageAccounts,
}: TargetDetailsProps) {
  const auth = target.authentication;
  const policy = target.security_policy;

  return (
    <div className="flex flex-col">
      <dl className="flex flex-col">
        <Row label="Status">
          <StatusPill tone={target.enabled ? "positive" : "neutral"}>
            {target.enabled ? "Enabled" : "Disabled"}
          </StatusPill>
        </Row>
        <Row label="Type">
          <span className="text-sm text-slate-200">{TARGET_TYPE_LABELS[target.type]}</span>
        </Row>
        <Row label="Environment">
          <span className="text-sm text-slate-200">
            {ENVIRONMENT_LABELS[target.environment]}
          </span>
        </Row>
        <Row label="Ownership">
          <span className="text-sm text-slate-200">
            {OWNERSHIP_STATUS_LABELS[target.ownership_status]}
          </span>
        </Row>
        <Row label="Base URL">
          <Link value={target.base_url} />
        </Row>
        <Row label="API URL">
          <Link value={target.api_url} />
        </Row>
        <Row label="Source path">
          <span className="font-mono text-sm break-all text-slate-300">
            {target.source_path ?? "not set"}
          </span>
        </Row>
        <Row label="Description">
          <span className="text-sm whitespace-pre-wrap text-slate-300">
            {target.description || "—"}
          </span>
        </Row>
        <Row label="Authentication">
          {auth.enabled ? (
            <div className="flex flex-col gap-1 text-sm text-slate-300">
              <span className="text-slate-200">{AUTH_METHOD_LABELS[auth.method]}</span>
              {auth.login_url ? <Link value={auth.login_url} /> : null}
              {auth.username_field || auth.password_field ? (
                <span className="font-mono text-xs text-slate-400">
                  {auth.username_field ?? "?"} / {auth.password_field ?? "?"}
                </span>
              ) : null}
              <span className="text-xs text-slate-500">
                Credential kept in {TOKEN_LOCATION_LABELS[auth.token_location]}. Not used
                yet &mdash; this is configuration only.
              </span>
            </div>
          ) : (
            <span className="text-sm text-slate-500">Not configured</span>
          )}
        </Row>
        <Row label="Testing policy">
          <div className="flex flex-col gap-2">
            <StatusPill tone={policy.authorized_for_testing ? "positive" : "neutral"}>
              {policy.authorized_for_testing
                ? "Authorized for testing"
                : "Not authorized"}
            </StatusPill>
            <ul className="flex flex-col gap-1">
              <Capability
                label="Security scanning"
                granted={policy.allow_security_scanning}
              />
              <Capability
                label="Authenticated testing"
                granted={policy.allow_authenticated_testing}
              />
              <Capability
                label="State-changing requests"
                granted={policy.allow_state_changing_requests}
              />
            </ul>
          </div>
        </Row>
        <Row label="Target ID">
          <span className="font-mono text-sm break-all text-slate-400">{target.id}</span>
        </Row>
        <Row label="Registered">
          <span className="text-sm text-slate-300">{formatTimestamp(target.created_at)}</span>
        </Row>
        <Row label="Last updated">
          <span className="text-sm text-slate-300">{formatTimestamp(target.updated_at)}</span>
        </Row>
      </dl>

      <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-slate-800 pt-4">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Close
        </button>
        <button
          type="button"
          onClick={() => onManageAccounts(target)}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Test accounts
        </button>
        <button
          type="button"
          onClick={() => onEdit(target)}
          className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400"
        >
          Edit
        </button>
      </div>
    </div>
  );
}
