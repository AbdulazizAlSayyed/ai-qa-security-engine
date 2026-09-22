import { Fragment, useEffect, useMemo, useState } from "react";

import StatusPill from "@/components/StatusPill";
import SeverityBadge from "@/components/security/SeverityBadge";
import { EVIDENCE_LABEL, EVIDENCE_TONE, evidenceRef, formatTime } from "@/lib/assessment";
import type { Evidence, EvidenceType } from "@/types/assessment";
import { SEVERITIES, type Severity } from "@/types/security";

type Filter = "all" | EvidenceType;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "qa", label: "QA" },
  { value: "security", label: "Security" },
];

function isSeverity(value: string | null): value is Severity {
  return value !== null && (SEVERITIES as readonly string[]).includes(value);
}

function Empty() {
  return <span className="text-slate-600">—</span>;
}

function TraceDetails({ item }: { item: Evidence }) {
  return (
    <div className="flex flex-col gap-2 px-4 py-3">
      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[8rem_1fr]">
        <dt className="text-slate-500">Reference</dt>
        <dd className="font-mono text-sky-300">{evidenceRef(item.sequence)}</dd>
        <dt className="text-slate-500">Expected</dt>
        <dd className="text-slate-300">{item.expected ?? "— (no meaningful expected value)"}</dd>
        <dt className="text-slate-500">Actual</dt>
        <dd className="font-mono break-all whitespace-pre-wrap text-slate-300">
          {item.actual ?? "—"}
        </dd>
        <dt className="text-slate-500">Traces to</dt>
        <dd className="font-mono break-all text-slate-300">
          {item.finding_type} run {item.source_run_id ?? "—"}
          {item.source_finding_id ? ` · ${item.source_finding_id}` : ""}
        </dd>
        <dt className="text-slate-500">Assessment</dt>
        <dd className="font-mono break-all text-slate-400">{item.assessment_id}</dd>
        <dt className="text-slate-500">Evidence id</dt>
        <dd className="font-mono break-all text-slate-400">{item.evidence_id}</dd>
        <dt className="text-slate-500">Recorded</dt>
        <dd className="text-slate-400">{new Date(item.timestamp).toLocaleString()}</dd>
      </dl>
      <details>
        <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300">
          Tool payload
        </summary>
        <pre className="mt-1.5 max-h-56 overflow-auto rounded bg-slate-950/80 p-2 font-mono text-[11px] text-slate-400">
          {JSON.stringify(item.evidence_payload, null, 2)}
        </pre>
      </details>
    </div>
  );
}

interface EvidenceTableProps {
  evidence: Evidence[];
  /**
   * Open, highlight and scroll to this record - used when an AI finding's
   * evidence reference is clicked. ``focusNonce`` re-triggers it for the
   * same record.
   */
  focusEvidenceId?: string | null;
  focusNonce?: number;
}

export default function EvidenceTable({
  evidence,
  focusEvidenceId = null,
  focusNonce = 0,
}: EvidenceTableProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    if (!focusEvidenceId) return;
    setFilter("all");
    setOpenId(focusEvidenceId);
    // Wait for the filter/expansion to render before scrolling.
    const timer = window.setTimeout(() => {
      document
        .getElementById(`evidence-row-${focusEvidenceId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    return () => window.clearTimeout(timer);
  }, [focusEvidenceId, focusNonce]);

  const visible = useMemo(
    () => (filter === "all" ? evidence : evidence.filter((e) => e.finding_type === filter)),
    [evidence, filter],
  );

  const counts = useMemo(
    () => ({
      all: evidence.length,
      qa: evidence.filter((e) => e.finding_type === "qa").length,
      security: evidence.filter((e) => e.finding_type === "security").length,
    }),
    [evidence],
  );

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">
          Normalized evidence ({evidence.length})
        </h2>
        <div className="flex gap-1" role="group" aria-label="Filter evidence">
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilter(value)}
              aria-pressed={filter === value}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                filter === value
                  ? "bg-sky-500/15 text-sky-300"
                  : "text-slate-400 hover:bg-slate-800/60"
              }`}
            >
              {label} <span className="font-mono text-slate-500">{counts[value]}</span>
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="mt-3 rounded-xl border border-dashed border-slate-800 p-6 text-center text-sm text-slate-500">
          No evidence in this view.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
          <table className="w-full min-w-[76rem] text-left text-xs">
            <thead className="border-b border-slate-800 text-[11px] tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="px-3 py-2 font-medium">Ref</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Category</th>
                <th className="px-3 py-2 font-medium">Check / finding</th>
                <th className="px-3 py-2 font-medium">Component</th>
                <th className="px-3 py-2 font-medium">Expected</th>
                <th className="px-3 py-2 font-medium">Actual</th>
                <th className="px-3 py-2 font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => {
                const open = openId === item.evidence_id;
                const focused = focusEvidenceId === item.evidence_id;
                return (
                  <Fragment key={item.evidence_id}>
                    <tr
                      id={`evidence-row-${item.evidence_id}`}
                      onClick={() => setOpenId(open ? null : item.evidence_id)}
                      className={`cursor-pointer border-b border-slate-800/60 align-top transition-colors hover:bg-slate-800/40 ${
                        focused
                          ? "bg-sky-500/10 ring-1 ring-sky-500/40 ring-inset"
                          : open
                            ? "bg-slate-800/30"
                            : ""
                      }`}
                    >
                      <td className="px-3 py-2 font-mono whitespace-nowrap text-sky-300">
                        {evidenceRef(item.sequence)}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-col items-start gap-1">
                          <StatusPill tone={EVIDENCE_TONE[item.status]}>
                            {EVIDENCE_LABEL[item.status]}
                          </StatusPill>
                          {isSeverity(item.tool_severity) ? (
                            <SeverityBadge severity={item.tool_severity} />
                          ) : null}
                        </div>
                      </td>
                      <td className="px-3 py-2 font-mono text-slate-300">{item.source}</td>
                      <td className="px-3 py-2 text-slate-400">{item.finding_type}</td>
                      <td className="px-3 py-2 font-mono text-slate-400">{item.category}</td>
                      <td className="min-w-40 max-w-64 px-3 py-2 text-slate-100">{item.title}</td>
                      <td className="min-w-44 max-w-64 px-3 py-2 font-mono break-all text-slate-300">
                        {item.target_component}
                      </td>
                      <td className="max-w-44 px-3 py-2 text-slate-300">
                        {item.expected ?? <Empty />}
                      </td>
                      <td className="min-w-48 max-w-72 px-3 py-2 font-mono break-all text-slate-300">
                        {item.actual ? (
                          <span className="line-clamp-3" title={item.actual}>
                            {item.actual}
                          </span>
                        ) : (
                          <Empty />
                        )}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-slate-500">
                        {formatTime(item.timestamp)}
                      </td>
                    </tr>
                    {open ? (
                      <tr className="border-b border-slate-800/60 bg-slate-950/50">
                        <td colSpan={10}>
                          <TraceDetails item={item} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
