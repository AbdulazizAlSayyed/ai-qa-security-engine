import { useState, type ReactNode } from "react";

import StatusPill from "@/components/StatusPill";
import SeverityBadge from "@/components/security/SeverityBadge";
import {
  COMPONENT_LABEL,
  COMPONENT_TONE,
  RUN_STATUS_LABEL,
  RUN_STATUS_TONE,
  componentTitle,
  formatDuration,
  formatTimestamp,
} from "@/lib/security";
import {
  SEVERITIES,
  type SecurityComponent,
  type SecurityFinding,
  type SecurityRun,
} from "@/types/security";

interface SecurityRunDetailsProps {
  run: SecurityRun;
  onClose: () => void;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs tracking-wide text-slate-500 uppercase">{label}</p>
      <div className="mt-0.5 text-sm break-all text-slate-200">{children}</div>
    </div>
  );
}

function FindingRow({ finding }: { finding: SecurityFinding }) {
  const [open, setOpen] = useState(false);

  return (
    <li className="rounded-lg border border-slate-800 bg-slate-950/50">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-left"
      >
        <span className="flex min-w-0 items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <span className="truncate text-sm text-slate-100">{finding.name}</span>
        </span>
        <span className="flex items-center gap-2">
          {finding.cwe ? (
            <span className="font-mono text-[11px] text-slate-500">CWE-{finding.cwe}</span>
          ) : null}
          <span className="font-mono text-xs text-slate-600">{open ? "−" : "+"}</span>
        </span>
      </button>

      {open ? (
        <div className="border-t border-slate-800/70 px-4 py-3">
          {finding.description ? (
            <p className="text-sm whitespace-pre-wrap text-slate-300">{finding.description}</p>
          ) : null}

          <dl className="mt-3 flex flex-col gap-1.5 text-xs">
            {finding.url ? (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-slate-500">Location</dt>
                <dd className="font-mono break-all text-slate-300">
                  {finding.method ? `${finding.method} ` : ""}
                  {finding.url}
                </dd>
              </div>
            ) : null}
            {finding.parameter ? (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-slate-500">Parameter</dt>
                <dd className="font-mono text-slate-300">{finding.parameter}</dd>
              </div>
            ) : null}
            {finding.evidence ? (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-slate-500">Evidence</dt>
                <dd className="font-mono break-all text-slate-300">{finding.evidence}</dd>
              </div>
            ) : null}
            {finding.solution ? (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-slate-500">Solution</dt>
                <dd className="whitespace-pre-wrap text-slate-300">{finding.solution}</dd>
              </div>
            ) : null}
            <div className="flex gap-2">
              <dt className="w-20 shrink-0 text-slate-500">Scanner</dt>
              <dd className="font-mono text-slate-400">
                {finding.source}
                {finding.rule_id ? ` · rule ${finding.rule_id}` : ""}
                {finding.confidence ? ` · ${finding.confidence} confidence` : ""}
              </dd>
            </div>
            {finding.reference ? (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-slate-500">Reference</dt>
                <dd className="break-all">
                  <a
                    href={finding.reference}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-sky-300 hover:underline"
                  >
                    {finding.reference}
                  </a>
                </dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}
    </li>
  );
}

function ComponentCard({ component }: { component: SecurityComponent }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-slate-100">
          {componentTitle(component.name)}
        </span>
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-600">
            {formatDuration(component.duration_ms)}
          </span>
          <StatusPill tone={COMPONENT_TONE[component.status]}>
            {COMPONENT_LABEL[component.status]}
          </StatusPill>
        </span>
      </div>

      {component.detail ? (
        <p className="mt-2 text-xs text-slate-400">{component.detail}</p>
      ) : null}

      <p className="mt-2 text-xs text-slate-500">
        {component.findings.length} finding{component.findings.length === 1 ? "" : "s"}
      </p>
    </div>
  );
}

export default function SecurityRunDetails({ run, onClose }: SecurityRunDetailsProps) {
  const bySource = run.findings.reduce<Record<string, SecurityFinding[]>>((acc, finding) => {
    (acc[finding.source] ??= []).push(finding);
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-5">
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="Target">{run.target_name}</Field>
        <Field label="Overall status">
          <StatusPill tone={RUN_STATUS_TONE[run.status]}>
            {RUN_STATUS_LABEL[run.status]}
          </StatusPill>
        </Field>
        <Field label="Base URL">
          <a
            href={run.target_base_url}
            target="_blank"
            rel="noreferrer noopener"
            className="font-mono text-sky-300 hover:underline"
          >
            {run.target_base_url}
          </a>
        </Field>
        <Field label="API URL">
          <span className="font-mono">{run.target_api_url ?? "not set"}</span>
        </Field>
        <Field label="Started">{formatTimestamp(run.started_at)}</Field>
        <Field label="Duration">{formatDuration(run.duration_ms)}</Field>
      </section>

      {run.error ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <p className="text-sm font-medium text-amber-200">The engine could not execute</p>
          <p className="mt-1 font-mono text-xs break-all text-amber-200/80">{run.error}</p>
        </div>
      ) : null}

      <section>
        <h3 className="text-sm font-semibold text-slate-200">Severity summary</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          {SEVERITIES.map((severity) => (
            <SeverityBadge key={severity} severity={severity} count={run.summary[severity]} />
          ))}
          <span className="inline-flex items-center rounded-md bg-slate-800/60 px-2 py-0.5 text-xs text-slate-300">
            Total <span className="ml-1.5 font-mono">{run.summary.total_findings}</span>
          </span>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-slate-200">Scanners</h3>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {run.components.map((component) => (
            <ComponentCard key={component.name} component={component} />
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-slate-200">Findings</h3>
        {run.findings.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">
            No findings were reported by any scanner.
          </p>
        ) : (
          Object.entries(bySource).map(([source, findings]) => (
            <div key={source} className="mt-3">
              <p className="text-xs tracking-wide text-slate-500 uppercase">
                {componentTitle(source === "api_probe" ? "api_probes" : source)} (
                {findings.length})
              </p>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {findings.map((finding) => (
                  <FindingRow key={finding.id} finding={finding} />
                ))}
              </ul>
            </div>
          ))
        )}
      </section>

      {Object.keys(run.engine_metadata ?? {}).length > 0 ? (
        <section>
          <h3 className="text-sm font-semibold text-slate-200">Scanner metadata</h3>
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {Object.entries(run.engine_metadata)
              .filter(([, value]) => typeof value !== "object")
              .map(([key, value]) => (
                <div key={key} className="flex gap-1 text-xs">
                  <dt className="text-slate-500">{key}:</dt>
                  <dd className="font-mono text-slate-400">{String(value)}</dd>
                </div>
              ))}
          </dl>
        </section>
      ) : null}

      <div className="flex justify-between gap-2 border-t border-slate-800 pt-4">
        <span className="font-mono text-xs text-slate-600">{run.id}</span>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Close
        </button>
      </div>
    </div>
  );
}
