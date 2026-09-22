import { useState, type FormEvent } from "react";

import {
  TARGET_TYPES,
  TARGET_TYPE_LABELS,
  type Target,
  type TargetCreate,
  type TargetType,
} from "@/types/target";

interface TargetFormProps {
  /** Present when editing; absent when registering a new target. */
  target?: Target;
  onSubmit: (values: TargetCreate) => Promise<void>;
  onCancel: () => void;
}

interface FormState {
  name: string;
  base_url: string;
  api_url: string;
  type: TargetType;
  source_path: string;
  description: string;
  enabled: boolean;
}

function initialState(target?: Target): FormState {
  return {
    name: target?.name ?? "",
    base_url: target?.base_url ?? "",
    api_url: target?.api_url ?? "",
    type: target?.type ?? "web_application",
    source_path: target?.source_path ?? "",
    description: target?.description ?? "",
    enabled: target?.enabled ?? true,
  };
}

/** Blank optional text means "not set", which the API models as null. */
function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

const fieldClass =
  "w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none";
const labelClass = "block text-sm font-medium text-slate-300";
const hintClass = "mt-1 text-xs text-slate-500";

export default function TargetForm({ target, onSubmit, onCancel }: TargetFormProps) {
  const [values, setValues] = useState<FormState>(() => initialState(target));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);

    try {
      await onSubmit({
        name: values.name.trim(),
        base_url: orNull(values.base_url),
        api_url: orNull(values.api_url),
        type: values.type,
        source_path: orNull(values.source_path),
        description: values.description.trim(),
        enabled: values.enabled,
      });
    } catch (caught) {
      // The backend is the source of truth on validation, so show what it said.
      setError(caught instanceof Error ? caught.message : "Could not save the target.");
      setIsSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label className={labelClass} htmlFor="target-name">
          Name <span className="text-rose-400">*</span>
        </label>
        <input
          id="target-name"
          className={`${fieldClass} mt-1`}
          value={values.name}
          onChange={(event) => set("name", event.target.value)}
          placeholder="Mini E-Commerce"
          maxLength={120}
          required
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="target-base-url">
            Base URL
          </label>
          <input
            id="target-base-url"
            className={`${fieldClass} mt-1 font-mono`}
            value={values.base_url}
            onChange={(event) => set("base_url", event.target.value)}
            placeholder="http://localhost:3000"
          />
          <p className={hintClass}>Where the UI is served.</p>
        </div>

        <div>
          <label className={labelClass} htmlFor="target-api-url">
            API URL
          </label>
          <input
            id="target-api-url"
            className={`${fieldClass} mt-1 font-mono`}
            value={values.api_url}
            onChange={(event) => set("api_url", event.target.value)}
            placeholder="http://localhost:4000"
          />
          <p className={hintClass}>Where the API is served.</p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="target-type">
            Type
          </label>
          <select
            id="target-type"
            className={`${fieldClass} mt-1`}
            value={values.type}
            onChange={(event) => set("type", event.target.value as TargetType)}
          >
            {TARGET_TYPES.map((type) => (
              <option key={type} value={type}>
                {TARGET_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelClass} htmlFor="target-source-path">
            Source path
          </label>
          <input
            id="target-source-path"
            className={`${fieldClass} mt-1 font-mono`}
            value={values.source_path}
            onChange={(event) => set("source_path", event.target.value)}
            placeholder="optional"
          />
          <p className={hintClass}>Only needed for static analysis later.</p>
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="target-description">
          Description
        </label>
        <textarea
          id="target-description"
          className={`${fieldClass} mt-1 min-h-20 resize-y`}
          value={values.description}
          onChange={(event) => set("description", event.target.value)}
          maxLength={2000}
          placeholder="What this application is and why it is registered."
        />
      </div>

      <label className="flex items-center gap-3 text-sm text-slate-300">
        <input
          type="checkbox"
          className="size-4 rounded border-slate-700 bg-slate-950 accent-sky-500"
          checked={values.enabled}
          onChange={(event) => set("enabled", event.target.checked)}
        />
        Enabled &mdash; assessments may run against this target
      </label>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
        >
          {error}
        </p>
      ) : null}

      <div className="flex justify-end gap-2 border-t border-slate-800 pt-4">
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
          className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSaving ? "Saving..." : target ? "Save changes" : "Register target"}
        </button>
      </div>
    </form>
  );
}
