import type { ReactNode } from "react";

import StatusPill from "@/components/StatusPill";
import {
  QA_STATUS_LABEL,
  QA_STATUS_TONE,
  formatDuration,
  formatTimestamp,
} from "@/lib/qa";
import type { QaRun, QaTestResult } from "@/types/qa";

interface QaRunDetailsProps {
  run: QaRun;
  onClose: () => void;
}

const STATUS_GLYPH: Record<string, string> = {
  passed: "✓",
  failed: "✗",
  error: "!",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs tracking-wide text-slate-500 uppercase">{label}</p>
      <div className="mt-0.5 text-sm break-all text-slate-200">{children}</div>
    </div>
  );
}

function TestRow({ test }: { test: QaTestResult }) {
  const tone = QA_STATUS_TONE[test.status];
  const glyphColor =
    test.status === "passed"
      ? "text-emerald-400"
      : test.status === "failed"
        ? "text-rose-400"
        : "text-amber-400";

  const detailEntries = Object.entries(test.details ?? {});

  return (
    <li className="rounded-lg border border-slate-800 bg-slate-950/50 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <span className={`font-mono ${glyphColor}`}>{STATUS_GLYPH[test.status]}</span>
          <span className="truncate text-sm text-slate-100">{test.name}</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-500">
            {formatDuration(test.duration_ms)}
          </span>
          <StatusPill tone={tone}>{QA_STATUS_LABEL[test.status]}</StatusPill>
        </span>
      </div>

      {test.error ? (
        <p className="mt-2 rounded border border-rose-500/25 bg-rose-500/5 px-2 py-1 font-mono text-xs break-all text-rose-200">
          {test.error}
        </p>
      ) : null}

      {detailEntries.length > 0 ? (
        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {detailEntries.map(([key, value]) => (
            <div key={key} className="flex gap-1 text-xs">
              <dt className="text-slate-500">{key}:</dt>
              <dd className="font-mono break-all text-slate-400">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  );
}

export default function QaRunDetails({ run, onClose }: QaRunDetailsProps) {
  return (
    <div className="flex flex-col gap-5">
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="Target">{run.target_name}</Field>
        <Field label="Base URL">
          <a
            href={run.target_base_url}
            target="_blank"
            rel="noreferrer noopener"
            className="font-mono text-sky-300 hover:text-sky-200 hover:underline"
          >
            {run.target_base_url}
          </a>
        </Field>
        <Field label="Started">{formatTimestamp(run.started_at)}</Field>
        <Field label="Finished">{formatTimestamp(run.finished_at)}</Field>
        <Field label="Duration">{formatDuration(run.duration_ms)}</Field>
        <Field label="Overall status">
          <StatusPill tone={QA_STATUS_TONE[run.status]}>
            {QA_STATUS_LABEL[run.status]}
          </StatusPill>
        </Field>
      </section>

      {run.error ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <p className="text-sm font-medium text-amber-200">The engine could not execute</p>
          <p className="mt-1 font-mono text-xs break-all text-amber-200/80">{run.error}</p>
        </div>
      ) : null}

      <section>
        <h3 className="text-sm font-semibold text-slate-200">Tests</h3>
        {run.tests.length > 0 ? (
          <ul className="mt-2 flex flex-col gap-2">
            {run.tests.map((test) => (
              <TestRow key={test.name} test={test} />
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No tests executed.</p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold text-slate-200">Observations</h3>
        <p className="mt-1 text-xs text-slate-500">
          Recorded, not judged. Later phases decide what they mean.
        </p>

        <div className="mt-3">
          <p className="text-xs tracking-wide text-slate-500 uppercase">
            Console errors ({run.console_errors.length})
          </p>
          {run.console_errors.length > 0 ? (
            <ul className="mt-1 flex flex-col gap-1">
              {run.console_errors.map((item, index) => (
                <li
                  key={`${item.message}-${index}`}
                  className="rounded border border-slate-800 bg-slate-950/50 px-3 py-2"
                >
                  <p className="font-mono text-xs break-all text-slate-300">{item.message}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-slate-600">
                    {item.type}
                    {item.location ? ` · ${item.location}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-sm text-slate-500">None.</p>
          )}
        </div>

        <div className="mt-4">
          <p className="text-xs tracking-wide text-slate-500 uppercase">
            Network failures ({run.network_failures.length})
          </p>
          {run.network_failures.length > 0 ? (
            <ul className="mt-1 flex flex-col gap-1">
              {run.network_failures.map((item, index) => (
                <li
                  key={`${item.url}-${index}`}
                  className="rounded border border-slate-800 bg-slate-950/50 px-3 py-2"
                >
                  <p className="font-mono text-xs break-all text-slate-300">
                    <span className="text-slate-500">{item.method}</span> {item.url}
                  </p>
                  <p className="mt-0.5 font-mono text-[11px] text-slate-600">
                    {item.status !== null ? `HTTP ${item.status}` : (item.failure ?? "failed")}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-sm text-slate-500">None.</p>
          )}
        </div>
      </section>

      {Object.keys(run.metadata ?? {}).length > 0 ? (
        <section>
          <h3 className="text-sm font-semibold text-slate-200">Engine</h3>
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {Object.entries(run.metadata).map(([key, value]) => (
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
