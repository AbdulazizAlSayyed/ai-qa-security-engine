import { useCallback, useEffect, useMemo, useState } from "react";

import Modal from "@/components/Modal";
import StatCard from "@/components/StatCard";
import CandidateReviewPanel from "@/components/requirements/CandidateReviewPanel";
import RequirementDetails from "@/components/requirements/RequirementDetails";
import RequirementForm from "@/components/requirements/RequirementForm";
import { useTargets } from "@/hooks/useTargets";
import { deleteRequirement, listRequirements } from "@/services/requirements";
import {
  AREA_LABELS,
  PRIORITY_LABELS,
  REQUIREMENT_AREAS,
  REQUIREMENT_PRIORITIES,
  REQUIREMENT_SOURCES,
  REQUIREMENT_STATUSES,
  SOURCE_LABELS,
  STATUS_LABELS,
} from "@/types/requirement";
import type { Requirement, RequirementFilters } from "@/types/requirement";

type Dialog =
  | { kind: "none" }
  | { kind: "create" }
  | { kind: "edit"; requirement: Requirement }
  | { kind: "view"; requirement: Requirement }
  | { kind: "import" };

const STATUS_TONE: Record<string, string> = {
  draft: "border-slate-600 text-slate-300",
  approved: "border-emerald-500/50 text-emerald-300",
  deprecated: "border-amber-500/50 text-amber-300",
};

const select =
  "rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none";

/**
 * The requirements registry, one target at a time.
 *
 * Target ownership is the organising idea, not a filter: the page asks which
 * application you mean before it shows anything, because REQ-001 only means
 * something next to the target it belongs to.
 */
export default function RequirementsPage() {
  const { targets, error: targetsError } = useTargets();

  const [targetId, setTargetId] = useState("");
  const [filters, setFilters] = useState<RequirementFilters>({});
  const [requirements, setRequirements] = useState<Requirement[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>({ kind: "none" });

  const selectable = useMemo(() => targets ?? [], [targets]);
  const target = selectable.find((candidate) => candidate.id === targetId);

  useEffect(() => {
    if (targetId || selectable.length === 0) return;
    setTargetId(selectable[0]?.id ?? "");
  }, [selectable, targetId]);

  const refresh = useCallback(async () => {
    if (!targetId) {
      setRequirements(null);
      return;
    }
    setIsLoading(true);
    try {
      setRequirements(await listRequirements(targetId, filters));
      setError(null);
    } catch (caught) {
      setRequirements(null);
      setError(caught instanceof Error ? caught.message : "Could not load the registry.");
    } finally {
      setIsLoading(false);
    }
  }, [targetId, filters]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = useCallback(
    async (requirement: Requirement) => {
      setDialog({ kind: "none" });
      try {
        const result = await deleteRequirement(requirement.target_id, requirement.id);
        setNotice(
          `${result.key} deleted. Deprecating instead would have kept the record and the key.`,
        );
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not delete it.");
      }
    },
    [refresh],
  );

  const counts = useMemo(() => {
    const list = requirements ?? [];
    return {
      total: list.length,
      approved: list.filter((item) => item.status === "approved").length,
      draft: list.filter((item) => item.status === "draft").length,
    };
  }, [requirements]);

  const setFilter = (key: keyof RequirementFilters, value: string) =>
    setFilters((current) => {
      const next = { ...current };
      if (value) (next[key] as string) = value;
      else delete next[key];
      return next;
    });

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Requirements</h1>
          <p className="mt-1 text-sm text-slate-400">
            What each registered application is supposed to do. Source-of-truth
            expectations — not test results, and nothing here has been tested.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={isLoading || !targetId}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? "Loading..." : "Refresh"}
        </button>
      </header>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <label className="block text-sm font-medium text-slate-300" htmlFor="req-target">
              Target
            </label>
            <select
              id="req-target"
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              className={`mt-1 w-full ${select}`}
            >
              {selectable.length === 0 ? (
                <option value="">No target registered</option>
              ) : (
                selectable.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))
              )}
            </select>
          </div>

          <button
            type="button"
            onClick={() => setDialog({ kind: "import" })}
            disabled={!targetId}
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            From a document
          </button>
          <button
            type="button"
            onClick={() => setDialog({ kind: "create" })}
            disabled={!targetId}
            className="rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            New requirement
          </button>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <select
            aria-label="Filter by status"
            value={filters.status ?? ""}
            onChange={(event) => setFilter("status", event.target.value)}
            className={select}
          >
            <option value="">Any status</option>
            {REQUIREMENT_STATUSES.map((value) => (
              <option key={value} value={value}>
                {STATUS_LABELS[value]}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter by priority"
            value={filters.priority ?? ""}
            onChange={(event) => setFilter("priority", event.target.value)}
            className={select}
          >
            <option value="">Any priority</option>
            {REQUIREMENT_PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {PRIORITY_LABELS[value]}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter by area"
            value={filters.area ?? ""}
            onChange={(event) => setFilter("area", event.target.value)}
            className={select}
          >
            <option value="">Any area</option>
            {REQUIREMENT_AREAS.map((value) => (
              <option key={value} value={value}>
                {AREA_LABELS[value]}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter by source"
            value={filters.source ?? ""}
            onChange={(event) => setFilter("source", event.target.value)}
            className={select}
          >
            <option value="">Any source</option>
            {REQUIREMENT_SOURCES.map((value) => (
              <option key={value} value={value}>
                {SOURCE_LABELS[value]}
              </option>
            ))}
          </select>
        </div>
      </section>

      {notice ? (
        <div className="flex items-start justify-between gap-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
          <p className="text-sm text-emerald-200">{notice}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss"
            className="text-emerald-300/70 hover:text-emerald-200"
          >
            &times;
          </button>
        </div>
      ) : null}

      {targetsError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load targets</p>
          <p className="mt-1 text-sm text-rose-200/80">Is the backend running?</p>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load requirements</p>
          <p className="mt-2 font-mono text-xs text-rose-200/60">{error}</p>
        </div>
      ) : null}

      {requirements && requirements.length > 0 ? (
        <section className="grid gap-4 sm:grid-cols-3">
          <StatCard label="Requirements" value={counts.total} />
          <StatCard label="Approved" value={counts.approved} tone="positive" />
          <StatCard label="Draft" value={counts.draft} />
        </section>
      ) : null}

      <section>
        {requirements && requirements.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-10 text-center">
            <p className="font-medium text-slate-200">Nothing in this registry yet.</p>
            <p className="mt-1 text-sm text-slate-400">
              Write one by hand, or read a business or OpenAPI document and accept what
              you agree with.
            </p>
          </div>
        ) : null}

        {requirements && requirements.length > 0 ? (
          <div className="divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
            {requirements.map((requirement) => (
              <button
                key={requirement.id}
                type="button"
                onClick={() => setDialog({ kind: "view", requirement })}
                className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-800/40"
              >
                <span className="w-20 shrink-0 font-mono text-xs text-sky-300">
                  {requirement.key}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-slate-100">
                  {requirement.title}
                </span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs ${
                    STATUS_TONE[requirement.status] ?? "border-slate-600 text-slate-300"
                  }`}
                >
                  {STATUS_LABELS[requirement.status]}
                </span>
                <span className="text-xs text-slate-400">
                  {PRIORITY_LABELS[requirement.priority]}
                </span>
                <span className="text-xs text-slate-500">
                  {AREA_LABELS[requirement.area]}
                </span>
                <span className="text-xs text-slate-600">
                  {SOURCE_LABELS[requirement.source]}
                </span>
                <span className="text-xs text-slate-600">
                  {requirement.acceptance_criteria.length} AC
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {dialog.kind === "create" && target ? (
        <Modal title="New requirement" subtitle={target.name} onClose={() => setDialog({ kind: "none" })}>
          <RequirementForm
            targetId={target.id}
            targetName={target.name}
            onSaved={(saved) => {
              setDialog({ kind: "none" });
              setNotice(`${saved.key} created.`);
              void refresh();
            }}
            onCancel={() => setDialog({ kind: "none" })}
          />
        </Modal>
      ) : null}

      {dialog.kind === "edit" && target ? (
        <Modal
          title={`Edit ${dialog.requirement.key}`}
          subtitle={target.name}
          onClose={() => setDialog({ kind: "none" })}
        >
          <RequirementForm
            targetId={target.id}
            targetName={target.name}
            requirement={dialog.requirement}
            onSaved={(saved) => {
              setDialog({ kind: "none" });
              setNotice(`${saved.key} updated.`);
              void refresh();
            }}
            onCancel={() => setDialog({ kind: "none" })}
          />
        </Modal>
      ) : null}

      {dialog.kind === "view" ? (
        <Modal
          title={dialog.requirement.key}
          subtitle={target?.name}
          onClose={() => setDialog({ kind: "none" })}
        >
          <RequirementDetails
            requirement={dialog.requirement}
            targetName={target?.name ?? dialog.requirement.target_id}
            onEdit={() => setDialog({ kind: "edit", requirement: dialog.requirement })}
            onDelete={() => void handleDelete(dialog.requirement)}
            onClose={() => setDialog({ kind: "none" })}
          />
        </Modal>
      ) : null}

      {dialog.kind === "import" && target ? (
        <Modal
          title="Propose requirements from a document"
          subtitle={target.name}
          onClose={() => setDialog({ kind: "none" })}
        >
          <CandidateReviewPanel
            targetId={target.id}
            targetName={target.name}
            onImported={(count) => {
              setDialog({ kind: "none" });
              setNotice(`${count} requirement(s) written from the candidates you accepted.`);
              void refresh();
            }}
            onClose={() => setDialog({ kind: "none" })}
          />
        </Modal>
      ) : null}
    </div>
  );
}
