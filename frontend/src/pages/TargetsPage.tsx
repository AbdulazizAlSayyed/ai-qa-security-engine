import { useCallback, useState } from "react";

import Modal from "@/components/Modal";
import StatCard from "@/components/StatCard";
import TargetCard from "@/components/targets/TargetCard";
import TargetDetails from "@/components/targets/TargetDetails";
import TargetForm from "@/components/targets/TargetForm";
import { useTargets } from "@/hooks/useTargets";
import { createTarget, deleteTarget, updateTarget } from "@/services/targets";
import type { Target, TargetCreate } from "@/types/target";

type Dialog =
  | { kind: "none" }
  | { kind: "create" }
  | { kind: "edit"; target: Target }
  | { kind: "details"; target: Target }
  | { kind: "delete"; target: Target };

export default function TargetsPage() {
  const { targets, error, isLoading, refresh } = useTargets();

  const [dialog, setDialog] = useState<Dialog>({ kind: "none" });
  const [notice, setNotice] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const close = useCallback(() => setDialog({ kind: "none" }), []);

  const handleCreate = useCallback(
    async (values: TargetCreate) => {
      const created = await createTarget(values);
      close();
      setNotice(`Registered "${created.name}".`);
      await refresh();
    },
    [close, refresh],
  );

  const handleUpdate = useCallback(
    async (id: string, values: TargetCreate) => {
      const updated = await updateTarget(id, values);
      close();
      setNotice(`Updated "${updated.name}".`);
      await refresh();
    },
    [close, refresh],
  );

  const handleDelete = useCallback(
    async (target: Target) => {
      setIsDeleting(true);
      setDeleteError(null);
      try {
        await deleteTarget(target.id);
        close();
        setNotice(`Deleted "${target.name}".`);
        await refresh();
      } catch (caught) {
        setDeleteError(
          caught instanceof Error ? caught.message : "Could not delete the target.",
        );
      } finally {
        setIsDeleting(false);
      }
    },
    [close, refresh],
  );

  const enabledCount = targets?.filter((target) => target.enabled).length ?? 0;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Targets</h1>
          <p className="mt-1 text-sm text-slate-400">
            Applications this platform is authorised to assess.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={isLoading}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Loading..." : "Refresh"}
          </button>
          <button
            type="button"
            onClick={() => setDialog({ kind: "create" })}
            className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400"
          >
            Add target
          </button>
        </div>
      </header>

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

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load targets</p>
          <p className="mt-1 text-sm text-rose-200/80">
            Please make sure the backend is running.
          </p>
          <p className="mt-2 font-mono text-xs text-rose-200/60">{error}</p>
        </div>
      ) : null}

      {targets && targets.length > 0 ? (
        <section className="grid gap-4 sm:grid-cols-3">
          <StatCard label="Registered" value={targets.length} />
          <StatCard
            label="Enabled"
            value={enabledCount}
            tone={enabledCount > 0 ? "positive" : "neutral"}
          />
          <StatCard label="Disabled" value={targets.length - enabledCount} />
        </section>
      ) : null}

      {isLoading && targets === null ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center">
          <p className="text-sm text-slate-400">Loading targets...</p>
        </div>
      ) : null}

      {targets && targets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-10 text-center">
          <p className="font-medium text-slate-200">No targets registered yet.</p>
          <p className="mt-1 text-sm text-slate-400">
            Add a target to start building your assessment inventory.
          </p>
          <button
            type="button"
            onClick={() => setDialog({ kind: "create" })}
            className="mt-5 rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400"
          >
            Add target
          </button>
        </div>
      ) : null}

      {targets && targets.length > 0 ? (
        <section className="grid gap-4 lg:grid-cols-2">
          {targets.map((target) => (
            <TargetCard
              key={target.id}
              target={target}
              onView={(selected) => setDialog({ kind: "details", target: selected })}
              onEdit={(selected) => setDialog({ kind: "edit", target: selected })}
              onDelete={(selected) => {
                setDeleteError(null);
                setDialog({ kind: "delete", target: selected });
              }}
            />
          ))}
        </section>
      ) : null}

      {dialog.kind === "create" ? (
        <Modal
          title="Register a target"
          subtitle="The QA and security engines will assess this application."
          onClose={close}
        >
          <TargetForm onSubmit={handleCreate} onCancel={close} />
        </Modal>
      ) : null}

      {dialog.kind === "edit" ? (
        <Modal title="Edit target" subtitle={dialog.target.name} onClose={close}>
          <TargetForm
            target={dialog.target}
            onSubmit={(values) => handleUpdate(dialog.target.id, values)}
            onCancel={close}
          />
        </Modal>
      ) : null}

      {dialog.kind === "details" ? (
        <Modal title={dialog.target.name} subtitle="Registered target" onClose={close}>
          <TargetDetails
            target={dialog.target}
            onClose={close}
            onEdit={(selected) => setDialog({ kind: "edit", target: selected })}
          />
        </Modal>
      ) : null}

      {dialog.kind === "delete" ? (
        <Modal title="Delete target" subtitle={dialog.target.name} onClose={close}>
          <p className="text-sm text-slate-300">
            This removes <span className="font-medium text-slate-100">{dialog.target.name}</span>{" "}
            from the registry. The application itself is not touched.
          </p>

          {deleteError ? (
            <p
              role="alert"
              className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
            >
              {deleteError}
            </p>
          ) : null}

          <div className="mt-5 flex justify-end gap-2 border-t border-slate-800 pt-4">
            <button
              type="button"
              onClick={close}
              disabled={isDeleting}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleDelete(dialog.target)}
              disabled={isDeleting}
              className="rounded-lg bg-rose-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isDeleting ? "Deleting..." : "Delete target"}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
