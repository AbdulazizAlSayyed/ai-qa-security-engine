import { useCallback, useEffect, useRef, useState } from "react";

import StatusPill, { type Tone } from "@/components/StatusPill";
import { formatDuration, formatTimestamp } from "@/lib/assessment";
import { generateReport, listReports, reportFileUrl } from "@/services/reports";
import type { Assessment } from "@/types/assessment";
import type { Report } from "@/types/reports";

const STATUS: Record<Report["status"], { label: string; tone: Tone }> = {
  running: { label: "Generating", tone: "neutral" },
  completed: { label: "Completed", tone: "positive" },
  failed: { label: "Failed", tone: "negative" },
};

function formatBytes(size: number): string {
  return size >= 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;
}

function ReportCard({ report, assessmentId }: { report: Report; assessmentId: string }) {
  const status = STATUS[report.status];
  const snap = report.source_snapshot;
  const trace = report.traceability;
  const html = report.artifacts.html;
  const pdf = report.artifacts.pdf;
  return (
    <li className="rounded-xl border border-slate-800 bg-slate-950/50 p-4" data-testid="report-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-slate-100">{report.report_id}</span>
          <span data-testid={`report-status-${report.status}`}>
            <StatusPill tone={status.tone} pulse={report.status === "running"}>
              {status.label}
            </StatusPill>
          </span>
          {trace ? (
            <span
              className={`text-xs ${trace.status === "passed" ? "text-emerald-300" : "text-rose-300"}`}
              data-testid="report-traceability"
            >
              Traceability {trace.status} · {trace.links_checked} references checked
            </span>
          ) : null}
        </div>
        {report.status === "completed" ? (
          <div className="flex flex-wrap gap-2">
            {html ? (
              <a
                href={reportFileUrl(assessmentId, report.report_id, "html")}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-lg border border-sky-500/40 px-3 py-1.5 text-xs text-sky-200 hover:bg-sky-500/10"
                aria-label={`Open HTML report ${report.report_id}`}
              >
                Open HTML · {formatBytes(html.size_bytes)}
              </a>
            ) : null}
            {pdf ? (
              <a
                href={reportFileUrl(assessmentId, report.report_id, "pdf")}
                download={pdf.filename}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800/60"
                aria-label={`Download PDF report ${report.report_id}`}
              >
                Download PDF · {formatBytes(pdf.size_bytes)}
              </a>
            ) : null}
          </div>
        ) : null}
      </div>

      <p className="mt-2 text-xs text-slate-400">
        Generated {formatTimestamp(report.completed_at ?? report.created_at)} · {formatDuration(report.duration_ms)} · contract v
        {report.report_version}
        {report.source_fingerprint ? (
          <span className="font-mono text-slate-500"> · source {report.source_fingerprint.slice(0, 12)}</span>
        ) : null}
      </p>

      {snap ? (
        <dl className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          {[
            ["Evidence", snap.evidence_count],
            ["Issues", snap.issue_count],
            ["Recommendations", snap.recommendation_count],
            ["Retests", snap.retest_count],
            ["AI analysis", snap.ai_analysis_status],
            ["Correlation", snap.correlation_status],
            ["Partial", snap.partial ? "yes" : "no"],
            ["Assessment", snap.assessment_status],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-md bg-slate-900/70 px-2 py-1">
              <dt className="text-slate-500">{label}</dt>
              <dd className="text-slate-200">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {report.error ? (
        <div role="alert" className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs">
          <p className="font-medium text-rose-200">
            Not generated · <span className="font-mono">{report.error.category}</span>
          </p>
          <p className="mt-0.5 text-rose-200/80">{report.error.message}</p>
        </div>
      ) : null}

      {trace && trace.errors.length ? (
        <div className="mt-2">
          <p className="text-[11px] tracking-wide text-slate-500 uppercase">Broken references ({trace.errors.length})</p>
          <ul className="mt-1 flex flex-col gap-0.5 font-mono text-[11px] break-all text-rose-200/90">
            {trace.errors.slice(0, 10).map((item, index) => (
              <li key={`${item.relationship}-${item.source}-${item.reference}-${index}`}>
                {item.relationship}: {item.source} → {item.reference} ({item.problem})
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}

export default function ReportsPanel({ assessment }: { assessment: Assessment }) {
  const [reports, setReports] = useState<Report[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const inFlight = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    try {
      const items = await listReports(assessment.id, controller.signal);
      if (controller.signal.aborted) return;
      setReports(items);
      setLoadError(null);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setLoadError(caught instanceof Error ? caught.message : "Unexpected error");
    }
  }, [assessment.id]);

  useEffect(() => {
    void load();
    return () => inFlight.current?.abort();
  }, [load]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setRunError(null);
    setNotice(null);
    try {
      const created = await generateReport(assessment.id);
      setNotice(
        created.reused
          ? `The data has not changed since ${created.report_id}; that report was returned instead of a duplicate.`
          : `${created.report_id} generated.`,
      );
    } catch (caught) {
      // Failed attempts (e.g. broken traceability) are recorded; the re-read shows them.
      setRunError(caught instanceof Error ? caught.message : "The report could not be generated.");
    } finally {
      setGenerating(false);
      await load();
    }
  }, [assessment.id, load]);

  const blocker = assessment.status !== "completed" ? "A report needs a completed assessment." : null;
  const items = reports ?? [];

  return (
    <section
      id="reports"
      className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-5"
      aria-label="Reports"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-slate-100">Reports</h2>
            {generating ? (
              <span data-testid="report-generating">
                <StatusPill tone="neutral" pulse>
                  Generating
                </StatusPill>
              </span>
            ) : null}
          </div>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            A report assembles this assessment&apos;s stored records - evidence, AI analysis, prioritized issues,
            advisory recommendations and retests - into HTML and PDF, after checking that every stored reference
            resolves. Nothing is re-run and nothing is changed. Regenerating unchanged data returns the existing report.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleGenerate()}
          disabled={generating || Boolean(blocker)}
          title={blocker ?? undefined}
          className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {generating ? "Generating..." : "Generate Report"}
        </button>
      </div>

      {blocker ? <p className="mt-3 text-xs text-slate-500">{blocker}</p> : null}
      {notice ? (
        <p className="mt-3 text-sm text-emerald-300" data-testid="report-notice">
          {notice}
        </p>
      ) : null}
      {runError ? (
        <p role="alert" className="mt-3 text-sm text-rose-300" data-testid="report-error">
          {runError}
        </p>
      ) : null}
      {loadError ? (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          Could not load reports: {loadError}
        </p>
      ) : null}

      {reports && items.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500" data-testid="reports-empty">
          No reports yet. Generate one to get an HTML and a PDF of this assessment.
        </p>
      ) : null}

      {items.length > 0 ? (
        <ul className="mt-4 flex flex-col gap-3">
          {items.map((report) => (
            <ReportCard key={report.report_id} report={report} assessmentId={assessment.id} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
