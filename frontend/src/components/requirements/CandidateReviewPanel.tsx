import { useState } from "react";

import { extractFromBrd, extractFromOpenApi, importRequirements } from "@/services/requirements";
import {
  AREA_LABELS,
  PRIORITY_LABELS,
  REQUIREMENT_AREAS,
  REQUIREMENT_PRIORITIES,
  candidateToCreate,
} from "@/types/requirement";
import type {
  RequirementArea,
  RequirementCandidate,
  RequirementExtraction,
  RequirementPriority,
} from "@/types/requirement";

interface Props {
  targetId: string;
  targetName: string;
  onImported: (count: number) => void;
  onClose: () => void;
}

type Mode = "brd" | "openapi";

const field =
  "w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50";

/**
 * Read a document, then decide what to keep.
 *
 * The two halves of this panel are deliberately separate requests. Extracting
 * writes nothing: it returns proposals. Importing writes only the proposals a
 * person ticked, in whatever state they left them after editing. Nothing is
 * accepted by default, and there is no path from the first request to the
 * database that does not pass through the second.
 */
export default function CandidateReviewPanel({
  targetId,
  targetName,
  onImported,
  onClose,
}: Props) {
  const [mode, setMode] = useState<Mode>("brd");
  const [document, setDocument] = useState("");
  const [extraction, setExtraction] = useState<RequirementExtraction | null>(null);
  const [drafts, setDrafts] = useState<RequirementCandidate[]>([]);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExtract = async () => {
    setIsBusy(true);
    setError(null);
    try {
      const result =
        mode === "brd"
          ? await extractFromBrd(targetId, document)
          : await extractFromOpenApi(targetId, document);
      setExtraction(result);
      setDrafts(result.candidates.map((candidate) => ({ ...candidate })));
      // Nothing is accepted until a person says so.
      setAccepted(new Set());
    } catch (caught) {
      setExtraction(null);
      setDrafts([]);
      setError(caught instanceof Error ? caught.message : "The document could not be read.");
    } finally {
      setIsBusy(false);
    }
  };

  const handleImport = async () => {
    if (!extraction || accepted.size === 0) return;
    setIsBusy(true);
    setError(null);
    try {
      const payload = drafts
        .filter((_, index) => accepted.has(index))
        .map((candidate) => candidateToCreate(candidate, extraction.source));
      const result = await importRequirements(targetId, payload, extraction.extraction_id);
      onImported(result.count);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The requirements were not written.");
    } finally {
      setIsBusy(false);
    }
  };

  const edit = (index: number, patch: Partial<RequirementCandidate>) =>
    setDrafts((current) =>
      current.map((candidate, position) =>
        position === index ? { ...candidate, ...patch } : candidate,
      ),
    );

  const toggle = (index: number) =>
    setAccepted((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-slate-400">
        Proposing requirements for <span className="text-slate-200">{targetName}</span>.
        Reading a document stores nothing — only the candidates you tick are written.
      </p>

      <div className="flex flex-wrap gap-2">
        {(["brd", "openapi"] as Mode[]).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => {
              setMode(option);
              setExtraction(null);
              setDrafts([]);
              setAccepted(new Set());
            }}
            disabled={isBusy}
            className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
              mode === option
                ? "border-sky-500/50 bg-sky-500/10 text-sky-200"
                : "border-slate-700 text-slate-300 hover:bg-slate-800/60"
            }`}
          >
            {option === "brd" ? "Business document (AI)" : "OpenAPI document (offline)"}
          </button>
        ))}
      </div>

      <p className="text-xs text-slate-500">
        {mode === "brd"
          ? "The text is sent to the configured AI provider once, to be read. It is not stored."
          : "Parsed here, in the backend. The API this document describes is never contacted."}
      </p>

      <textarea
        value={document}
        onChange={(event) => setDocument(event.target.value)}
        disabled={isBusy}
        rows={10}
        placeholder={
          mode === "brd"
            ? "Paste the business document, user stories or specification text."
            : "Paste the OpenAPI 3.x document (JSON or YAML)."
        }
        className={`${field} font-mono text-xs`}
      />

      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-slate-500">{document.length} characters</span>
        <button
          type="button"
          onClick={() => void handleExtract()}
          disabled={isBusy || document.trim().length === 0}
          className="rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isBusy ? "Reading..." : "Propose candidates"}
        </button>
      </div>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
        >
          {error}
        </p>
      ) : null}

      {extraction ? (
        <section className="flex flex-col gap-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <p className="text-sm text-slate-200">
              {drafts.length} candidate{drafts.length === 1 ? "" : "s"} — none stored yet
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {extraction.provider
                ? `${extraction.provider} / ${extraction.model}`
                : "Parsed offline; no model involved"}{" "}
              · extraction{" "}
              <span className="font-mono">{extraction.extraction_id.slice(0, 12)}</span>
            </p>
            {extraction.notes.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-400">
                {extraction.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </div>

          {drafts.map((candidate, index) => (
            <article
              key={`${candidate.source_reference}-${index}`}
              className={`rounded-lg border p-3 ${
                accepted.has(index)
                  ? "border-emerald-500/40 bg-emerald-500/5"
                  : "border-slate-800 bg-slate-950/40"
              }`}
            >
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={accepted.has(index)}
                  onChange={() => toggle(index)}
                  disabled={isBusy}
                  className="size-4 accent-emerald-400"
                />
                Accept this candidate
              </label>

              <div className="mt-3 flex flex-col gap-2">
                <input
                  value={candidate.title}
                  onChange={(event) => edit(index, { title: event.target.value })}
                  disabled={isBusy}
                  maxLength={200}
                  aria-label="Candidate title"
                  className={field}
                />
                <textarea
                  value={candidate.description}
                  onChange={(event) => edit(index, { description: event.target.value })}
                  disabled={isBusy}
                  rows={3}
                  maxLength={4000}
                  aria-label="Candidate description"
                  className={field}
                />
                <div className="grid gap-2 sm:grid-cols-3">
                  <select
                    value={candidate.area}
                    onChange={(event) =>
                      edit(index, { area: event.target.value as RequirementArea })
                    }
                    disabled={isBusy}
                    aria-label="Candidate area"
                    className={field}
                  >
                    {REQUIREMENT_AREAS.map((area) => (
                      <option key={area} value={area}>
                        {AREA_LABELS[area]}
                      </option>
                    ))}
                  </select>
                  <select
                    value={candidate.priority}
                    onChange={(event) =>
                      edit(index, { priority: event.target.value as RequirementPriority })
                    }
                    disabled={isBusy}
                    aria-label="Candidate priority"
                    className={field}
                  >
                    {REQUIREMENT_PRIORITIES.map((priority) => (
                      <option key={priority} value={priority}>
                        {PRIORITY_LABELS[priority]}
                      </option>
                    ))}
                  </select>
                  <input
                    value={candidate.source_reference}
                    onChange={(event) =>
                      edit(index, { source_reference: event.target.value })
                    }
                    disabled={isBusy}
                    maxLength={300}
                    aria-label="Candidate source reference"
                    className={field}
                  />
                </div>
                <textarea
                  value={candidate.acceptance_criteria.join("\n")}
                  onChange={(event) =>
                    edit(index, {
                      acceptance_criteria: event.target.value
                        .split("\n")
                        .map((line) => line.trim())
                        .filter((line) => line.length > 0),
                    })
                  }
                  disabled={isBusy}
                  rows={3}
                  aria-label="Candidate acceptance criteria, one per line"
                  placeholder="One acceptance criterion per line"
                  className={field}
                />
              </div>

              {candidate.note ? (
                <p className="mt-2 text-xs text-slate-500">{candidate.note}</p>
              ) : null}
            </article>
          ))}

          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-slate-400">
              {accepted.size} of {drafts.length} accepted
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={isBusy}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:opacity-50"
              >
                Discard
              </button>
              <button
                type="button"
                onClick={() => void handleImport()}
                disabled={isBusy || accepted.size === 0}
                className="rounded-lg bg-emerald-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isBusy ? "Writing..." : `Write ${accepted.size} requirement(s)`}
              </button>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
