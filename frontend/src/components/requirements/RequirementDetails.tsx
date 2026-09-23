import {
  AREA_LABELS,
  PRIORITY_LABELS,
  SOURCE_LABELS,
  STATUS_LABELS,
} from "@/types/requirement";
import type { Requirement } from "@/types/requirement";

interface Props {
  requirement: Requirement;
  targetName: string;
  onEdit: () => void;
  onDelete: () => void;
  onClose: () => void;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-200">{children}</dd>
    </div>
  );
}

function when(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/**
 * Everything the registry holds about one requirement.
 *
 * Note what is deliberately absent: no coverage, no linked tests, no
 * pass/fail. Nothing in this phase tests a requirement, so showing a
 * verification state here would be showing something that does not exist.
 */
export default function RequirementDetails({
  requirement,
  targetName,
  onEdit,
  onDelete,
  onClose,
}: Props) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <p className="font-mono text-xs text-sky-300">{requirement.key}</p>
        <h3 className="mt-1 text-lg font-semibold text-slate-100">{requirement.title}</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">
          {requirement.description}
        </p>
      </div>

      <dl className="grid gap-4 sm:grid-cols-3">
        <Row label="Target">{targetName}</Row>
        <Row label="Status">{STATUS_LABELS[requirement.status]}</Row>
        <Row label="Priority">{PRIORITY_LABELS[requirement.priority]}</Row>
        <Row label="Area">{AREA_LABELS[requirement.area]}</Row>
        <Row label="Source">{SOURCE_LABELS[requirement.source]}</Row>
        <Row label="Source reference">
          {requirement.source_reference || <span className="text-slate-500">—</span>}
        </Row>
        <Row label="Created">{when(requirement.created_at)}</Row>
        <Row label="Updated">{when(requirement.updated_at)}</Row>
        {requirement.extraction_id ? (
          <Row label="Accepted from extraction">
            <span className="font-mono text-xs text-slate-400">
              {requirement.extraction_id}
            </span>
          </Row>
        ) : null}
      </dl>

      <div>
        <p className="mb-2 text-sm font-medium text-slate-300">
          Acceptance criteria ({requirement.acceptance_criteria.length})
        </p>
        {requirement.acceptance_criteria.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-sm text-slate-500">
            None recorded.
          </p>
        ) : (
          <ul className="divide-y divide-slate-800 overflow-hidden rounded-lg border border-slate-800">
            {requirement.acceptance_criteria.map((criterion) => (
              <li key={criterion.id} className="flex gap-3 bg-slate-950/40 px-3 py-2">
                <span className="w-16 shrink-0 font-mono text-xs text-slate-500">
                  {criterion.id}
                </span>
                <span className="text-sm text-slate-200">{criterion.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onDelete}
          className="rounded-lg border border-rose-500/40 px-4 py-2 text-sm text-rose-300 transition-colors hover:bg-rose-500/10"
        >
          Delete
        </button>
        <button
          type="button"
          onClick={onEdit}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Edit
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400"
        >
          Close
        </button>
      </div>
    </div>
  );
}
