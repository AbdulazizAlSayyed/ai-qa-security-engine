import type { AcceptanceCriterion } from "@/types/requirement";

interface Props {
  criteria: AcceptanceCriterion[];
  onChange: (criteria: AcceptanceCriterion[]) => void;
  disabled?: boolean;
}

/**
 * Structured acceptance criteria, one row each.
 *
 * The ids are the backend's, not this component's. A criterion that already
 * has one shows it and sends it back unchanged, which is what keeps AC-002
 * meaning the same statement after five edits. A new row carries `id: null`
 * and is labelled "new" until it has been saved and given a number - this
 * component never invents an id, because a number it made up would collide
 * with the real series.
 *
 * Reordering moves rows without touching ids, so a reordered criterion keeps
 * its reference. That is the whole point of having one.
 */
export default function AcceptanceCriteriaEditor({ criteria, onChange, disabled }: Props) {
  const replace = (index: number, text: string) => {
    onChange(
      criteria.map((criterion, position) =>
        position === index ? { ...criterion, text } : criterion,
      ),
    );
  };

  const remove = (index: number) => {
    onChange(criteria.filter((_, position) => position !== index));
  };

  const move = (index: number, delta: number) => {
    const destination = index + delta;
    const moved = criteria[index];
    const displaced = criteria[destination];
    if (!moved || !displaced) return;
    const next = criteria.slice();
    next[index] = displaced;
    next[destination] = moved;
    onChange(next);
  };

  const add = () => onChange([...criteria, { id: null, text: "" }]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-300">Acceptance criteria</span>
        <button
          type="button"
          onClick={add}
          disabled={disabled}
          className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Add criterion
        </button>
      </div>

      {criteria.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-sm text-slate-500">
          No criteria yet. A requirement without them is still a requirement — it just
          cannot be checked as true or false.
        </p>
      ) : null}

      {criteria.map((criterion, index) => (
        <div
          key={criterion.id ?? `new-${index}`}
          className="flex items-start gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-2"
        >
          <span
            className="mt-2 w-16 shrink-0 font-mono text-xs text-slate-500"
            title={
              criterion.id
                ? "Stable reference, allocated by the registry"
                : "Gets its number when this requirement is saved"
            }
          >
            {criterion.id ?? "new"}
          </span>

          <textarea
            value={criterion.text}
            onChange={(event) => replace(index, event.target.value)}
            disabled={disabled}
            rows={2}
            placeholder="A condition that must hold for this requirement to be met."
            className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50"
          />

          <div className="flex shrink-0 flex-col gap-1">
            <button
              type="button"
              onClick={() => move(index, -1)}
              disabled={disabled || index === 0}
              aria-label={`Move ${criterion.id ?? "this criterion"} up`}
              className="rounded border border-slate-700 px-2 text-xs text-slate-300 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-30"
            >
              ↑
            </button>
            <button
              type="button"
              onClick={() => move(index, 1)}
              disabled={disabled || index === criteria.length - 1}
              aria-label={`Move ${criterion.id ?? "this criterion"} down`}
              className="rounded border border-slate-700 px-2 text-xs text-slate-300 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-30"
            >
              ↓
            </button>
            <button
              type="button"
              onClick={() => remove(index)}
              disabled={disabled}
              aria-label={`Remove ${criterion.id ?? "this criterion"}`}
              className="rounded border border-rose-500/40 px-2 text-xs text-rose-300 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-30"
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
