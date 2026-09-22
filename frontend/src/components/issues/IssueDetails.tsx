import type { ReactNode } from "react";

import PriorityBadge from "@/components/issues/PriorityBadge";
import { RULE_LABEL } from "@/components/issues/rules";
import SeverityBadge from "@/components/security/SeverityBadge";
import type { Evidence } from "@/types/assessment";
import type { Issue } from "@/types/issues";

interface IssueDetailsProps {
  issue: Issue;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[10rem_1fr] sm:gap-4">
      <dt className="text-[11px] tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="min-w-0 text-sm text-slate-200">{children}</dd>
    </div>
  );
}

export default function IssueDetails({ issue, evidenceById, onShowEvidence }: IssueDetailsProps) {
  const verdict = issue.priority_reasons[issue.priority_reasons.length - 1];
  const notCounted = issue.priority_reasons.filter((reason) => reason.includes("not counted"));

  return (
    <div className="flex flex-col gap-4 px-4 py-4">
      <p className="text-sm text-slate-300">{issue.description}</p>

      <dl className="flex flex-col gap-3">
        <Row label="Type">{issue.type === "security" ? "Security" : "QA"}</Row>
        <Row label="Priority">
          <span className="flex flex-wrap items-center gap-2">
            <PriorityBadge priority={issue.priority} />
            <span className="font-mono text-xs text-slate-400">
              score {issue.priority_score} · model v{issue.priority_model_version}
            </span>
          </span>
        </Row>
        <Row label="Why this priority?">
          <table className="w-full max-w-xl text-left text-xs">
            <tbody>
              {issue.score_factors.map((factor) => (
                <tr key={factor.factor} className="border-b border-slate-800/60 last:border-0">
                  <td className="py-1 pr-3 font-mono text-slate-500">{factor.factor}</td>
                  <td className="py-1 pr-3 text-slate-300">{factor.detail}</td>
                  <td className="py-1 text-right font-mono text-slate-200">+{factor.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {notCounted.map((reason) => (
            <p key={reason} className="mt-1 text-xs text-amber-300/80">
              {reason}
            </p>
          ))}
          {verdict ? <p className="mt-1 text-xs text-slate-400">{verdict}</p> : null}
        </Row>
        <Row label="Tool severity">
          {issue.tool_severity ? (
            <span className="flex items-center gap-2">
              <SeverityBadge severity={issue.tool_severity} />
              <span className="text-xs text-slate-500">as reported by the scanner</span>
            </span>
          ) : (
            <span className="text-slate-500">— (QA checks carry no tool severity)</span>
          )}
        </Row>
        <Row label="Affected components">
          <ul className="flex flex-col gap-0.5 font-mono text-xs break-all text-slate-300">
            {issue.affected_components.map((component) => (
              <li key={component}>{component}</li>
            ))}
          </ul>
        </Row>
        <Row label="Sources">
          <span className="font-mono text-xs">{issue.sources.join(", ")}</span>
        </Row>
        <Row label="Correlation">
          <span className="font-mono text-xs text-slate-400">{issue.correlation_group_id}</span>{" "}
          · {RULE_LABEL[issue.correlation_rule] ?? issue.correlation_rule}
        </Row>
        <Row label={`Evidence (${issue.evidence_count})`}>
          <div className="flex flex-wrap gap-1.5">
            {issue.evidence_ids.map((evidenceId, index) => {
              const record = evidenceById.get(evidenceId);
              const ref = issue.evidence_refs[index] ?? evidenceId.slice(0, 8);
              return (
                <button
                  key={evidenceId}
                  type="button"
                  onClick={() => onShowEvidence(evidenceId)}
                  aria-label={`Show evidence ${ref}${record ? `: ${record.title}` : ""}`}
                  title={
                    record
                      ? `${record.source} · ${record.title} · ${record.target_component}`
                      : evidenceId
                  }
                  className="rounded-md border border-sky-500/30 bg-sky-500/5 px-2 py-0.5 font-mono text-[11px] text-sky-300 transition-colors hover:bg-sky-500/15"
                >
                  {ref}
                </button>
              );
            })}
          </div>
        </Row>
        <Row label="AI findings">
          {issue.ai_findings.length === 0 ? (
            <span className="text-slate-500">
              None linked{issue.ai_analysis_id ? "" : " (no completed AI analysis was used)"}
            </span>
          ) : (
            <ul className="flex flex-col gap-1">
              {issue.ai_findings.map((finding) => (
                <li key={finding.finding_id} className="text-xs text-slate-300">
                  <span className="font-mono text-slate-400">{finding.finding_id}</span> ·{" "}
                  {finding.title} ·{" "}
                  <span className="text-slate-500">
                    {finding.status === "supported" ? "supported" : "insufficient evidence"},{" "}
                    {finding.confidence} confidence (AI interpretation) · cites{" "}
                    {finding.evidence_refs.join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Row>
      </dl>
    </div>
  );
}
