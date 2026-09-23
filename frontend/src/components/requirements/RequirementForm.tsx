import { useState } from "react";

import AcceptanceCriteriaEditor from "@/components/requirements/AcceptanceCriteriaEditor";
import { createRequirement, updateRequirement } from "@/services/requirements";
import {
  AREA_LABELS,
  EMPTY_REQUIREMENT,
  PRIORITY_LABELS,
  REQUIREMENT_AREAS,
  REQUIREMENT_PRIORITIES,
  REQUIREMENT_SOURCES,
  REQUIREMENT_STATUSES,
  SOURCE_LABELS,
  STATUS_LABELS,
} from "@/types/requirement";
import type {
  Requirement,
  RequirementArea,
  RequirementCreate,
  RequirementPriority,
  RequirementSource,
  RequirementStatus,
} from "@/types/requirement";

interface Props {
  targetId: string;
  targetName: string;
  /** Present when editing; absent when writing a new requirement. */
  requirement?: Requirement;
  onSaved: (requirement: Requirement) => void;
  onCancel: () => void;
}

const field =
  "mt-1 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50";
const label = "block text-sm font-medium text-slate-300";

function toDraft(requirement?: Requirement): RequirementCreate {
  if (!requirement) return { ...EMPTY_REQUIREMENT, acceptance_criteria: [] };
  return {
    title: requirement.title,
    description: requirement.description,
    source: requirement.source,
    source_reference: requirement.source_reference,
    acceptance_criteria: requirement.acceptance_criteria.map((criterion) => ({
      ...criterion,
    })),
    area: requirement.area,
    priority: requirement.priority,
    status: requirement.status,
  };
}

/**
 * Write or edit one requirement.
 *
 * The form has no field for the REQ key, because the registry allocates it.
 * On an edit the whole acceptance-criteria list is sent: ids that come back
 * keep their criteria, a row with no id becomes a new one, and a row the
 * user removed is gone because it is simply absent from what is sent.
 */
export default function RequirementForm({
  targetId,
  targetName,
  requirement,
  onSaved,
  onCancel,
}: Props) {
  const [draft, setDraft] = useState<RequirementCreate>(() => toDraft(requirement));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof RequirementCreate>(key: K, value: RequirementCreate[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    try {
      const saved = requirement
        ? await updateRequirement(targetId, requirement.id, draft)
        : await createRequirement(targetId, draft);
      onSaved(saved);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the requirement.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
      <p className="text-sm text-slate-400">
        {requirement ? (
          <>
            Editing <span className="font-mono text-slate-200">{requirement.key}</span> on{" "}
            <span className="text-slate-200">{targetName}</span>. The key never changes.
          </>
        ) : (
          <>
            A new requirement for <span className="text-slate-200">{targetName}</span>. Its
            REQ key is allocated when you save.
          </>
        )}
      </p>

      <div>
        <label className={label} htmlFor="requirement-title">
          Title
        </label>
        <input
          id="requirement-title"
          value={draft.title}
          onChange={(event) => set("title", event.target.value)}
          disabled={isSaving}
          required
          maxLength={200}
          placeholder="Checkout rejects an order that exceeds available stock"
          className={field}
        />
      </div>

      <div>
        <label className={label} htmlFor="requirement-description">
          Description
        </label>
        <textarea
          id="requirement-description"
          value={draft.description}
          onChange={(event) => set("description", event.target.value)}
          disabled={isSaving}
          required
          rows={4}
          maxLength={4000}
          placeholder="The statement in full. What must be true of the application?"
          className={field}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={label} htmlFor="requirement-source">
            Source
          </label>
          <select
            id="requirement-source"
            value={draft.source}
            onChange={(event) => set("source", event.target.value as RequirementSource)}
            disabled={isSaving}
            className={field}
          >
            {REQUIREMENT_SOURCES.map((source) => (
              <option key={source} value={source}>
                {SOURCE_LABELS[source]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={label} htmlFor="requirement-source-reference">
            Source reference
          </label>
          <input
            id="requirement-source-reference"
            value={draft.source_reference}
            onChange={(event) => set("source_reference", event.target.value)}
            disabled={isSaving}
            maxLength={300}
            placeholder="BRD section 4.2, STORY-118, POST /api/orders"
            className={field}
          />
        </div>

        <div>
          <label className={label} htmlFor="requirement-area">
            Area
          </label>
          <select
            id="requirement-area"
            value={draft.area}
            onChange={(event) => set("area", event.target.value as RequirementArea)}
            disabled={isSaving}
            className={field}
          >
            {REQUIREMENT_AREAS.map((area) => (
              <option key={area} value={area}>
                {AREA_LABELS[area]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={label} htmlFor="requirement-priority">
            Priority
          </label>
          <select
            id="requirement-priority"
            value={draft.priority}
            onChange={(event) => set("priority", event.target.value as RequirementPriority)}
            disabled={isSaving}
            className={field}
          >
            {REQUIREMENT_PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {PRIORITY_LABELS[priority]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={label} htmlFor="requirement-status">
            Status
          </label>
          <select
            id="requirement-status"
            value={draft.status}
            onChange={(event) => set("status", event.target.value as RequirementStatus)}
            disabled={isSaving}
            className={field}
          >
            {REQUIREMENT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </div>
      </div>

      <AcceptanceCriteriaEditor
        criteria={draft.acceptance_criteria}
        onChange={(criteria) => set("acceptance_criteria", criteria)}
        disabled={isSaving}
      />

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
        >
          {error}
        </p>
      ) : null}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={isSaving}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSaving}
          className="rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSaving ? "Saving..." : requirement ? "Save changes" : "Create requirement"}
        </button>
      </div>
    </form>
  );
}
