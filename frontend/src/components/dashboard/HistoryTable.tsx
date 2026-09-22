import { Link, useNavigate } from "react-router-dom";

import StatusPill from "@/components/StatusPill";
import PriorityBadge from "@/components/issues/PriorityBadge";
import {
  ASSESSMENT_LABEL,
  ASSESSMENT_TONE,
  STAGE_LABEL,
  formatDuration,
  formatTimestamp,
} from "@/lib/assessment";
import type { HistoryItem } from "@/types/dashboard";
import { PRIORITIES } from "@/types/issues";

const AI_LABEL: Record<HistoryItem["ai_analysis_status"], string> = {
  not_analyzed: "—",
  running: "Running",
  completed: "Analyzed",
  failed: "Failed",
};

function Counts({ parts }: { parts: [string, number, string][] }) {
  return (
    <span className="font-mono tabular-nums">
      {parts.map(([label, value, tone], index) => (
        <span key={label} title={label}>
          {index > 0 ? <span className="text-slate-700"> / </span> : null}
          <span className={value > 0 ? tone : "text-slate-600"}>{value}</span>
        </span>
      ))}
    </span>
  );
}

function Issues({ item }: { item: HistoryItem }) {
  if (item.correlation_status !== "completed") {
    return (
      <span className="text-slate-600">
        {item.correlation_status === "not_correlated" ? "Not correlated" : item.correlation_status}
      </span>
    );
  }
  if (item.issues.total === 0) return <span className="text-slate-500">None</span>;
  return (
    <Link
      to={`/assessments/${item.id}#prioritized-issues`}
      onClick={(event) => event.stopPropagation()}
      className="flex flex-wrap gap-1"
      aria-label={`Open the prioritized issues of this assessment`}
    >
      {PRIORITIES.filter((level) => item.issues[level] > 0).map((level) => (
        <span key={level} className="flex items-center gap-0.5">
          <PriorityBadge priority={level} />
          <span className="font-mono text-slate-400">×{item.issues[level]}</span>
        </span>
      ))}
    </Link>
  );
}

/** Newest first. Every row opens the existing assessment detail page. */
export default function HistoryTable({ history }: { history: HistoryItem[] }) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
      <table className="w-full min-w-[64rem] text-left text-xs">
        <thead className="border-b border-slate-800 text-[11px] tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2 font-medium">Started</th>
            <th className="px-3 py-2 font-medium">Target</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Duration</th>
            <th className="px-3 py-2 font-medium" title="passed / failed / skipped / error">
              QA P/F/S/E
            </th>
            <th className="px-3 py-2 font-medium" title="high / medium / low / informational">
              Security H/M/L/I
            </th>
            <th className="px-3 py-2 font-medium">Findings</th>
            <th className="px-3 py-2 font-medium">AI</th>
            <th className="px-3 py-2 font-medium">Issues</th>
          </tr>
        </thead>
        <tbody>
          {history.map((item) => (
            <tr
              key={item.id}
              data-testid="history-row"
              onClick={() => navigate(`/assessments/${item.id}`)}
              className="cursor-pointer border-b border-slate-800/60 align-top transition-colors hover:bg-slate-800/40"
            >
              <td className="px-3 py-2 whitespace-nowrap text-slate-400">
                {formatTimestamp(item.started_at ?? item.created_at)}
              </td>
              <td className="px-3 py-2">
                <Link
                  to={`/assessments/${item.id}`}
                  onClick={(event) => event.stopPropagation()}
                  className="text-slate-100 hover:text-sky-300"
                >
                  {item.target_name}
                </Link>
              </td>
              <td className="px-3 py-2">
                <div className="flex flex-col items-start gap-1">
                  <StatusPill tone={ASSESSMENT_TONE[item.status]}>
                    {ASSESSMENT_LABEL[item.status]}
                  </StatusPill>
                  {item.partial ? (
                    <span
                      className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300"
                      title={`QA: ${STAGE_LABEL[item.qa_status]} · Security: ${STAGE_LABEL[item.security_status]}`}
                    >
                      Partial
                    </span>
                  ) : null}
                </div>
              </td>
              <td className="px-3 py-2 font-mono text-slate-400">{formatDuration(item.duration_ms)}</td>
              <td className="px-3 py-2">
                <Counts
                  parts={[
                    ["passed", item.qa.passed, "text-emerald-300"],
                    ["failed", item.qa.failed, "text-rose-300"],
                    ["skipped", item.qa.skipped, "text-slate-300"],
                    ["error", item.qa.error, "text-amber-300"],
                  ]}
                />
              </td>
              <td className="px-3 py-2">
                <Counts
                  parts={[
                    ["high", item.security.high, "text-rose-300"],
                    ["medium", item.security.medium, "text-amber-300"],
                    ["low", item.security.low, "text-sky-300"],
                    ["informational", item.security.informational, "text-slate-300"],
                  ]}
                />
              </td>
              <td className="px-3 py-2 font-mono text-slate-300">{item.total_findings}</td>
              <td className="px-3 py-2 text-slate-400">{AI_LABEL[item.ai_analysis_status]}</td>
              <td className="px-3 py-2">
                <Issues item={item} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
