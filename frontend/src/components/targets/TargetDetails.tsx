import type { ReactNode } from "react";

import StatusPill from "@/components/StatusPill";
import { TARGET_TYPE_LABELS, type Target } from "@/types/target";

interface TargetDetailsProps {
  target: Target;
  onClose: () => void;
  onEdit: (target: Target) => void;
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

export default function TargetDetails({ target, onClose, onEdit }: TargetDetailsProps) {
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

      <div className="mt-5 flex justify-end gap-2 border-t border-slate-800 pt-4">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Close
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
