import { NAVIGATION_LABELS } from "@/types/discovery";
import type { DiscoveredPage } from "@/types/discovery";

interface Props {
  page: DiscoveredPage;
  onClose: () => void;
}

/**
 * One discovered page: its forms, its fields and its controls.
 *
 * A field shows its name, type and reference — never a value, because none
 * was ever read. A form shows what it asks for; nothing here submitted one.
 */
export default function PageDetails({ page, onClose }: Props) {
  return (
    <div className="flex flex-col gap-5">
      <dl className="grid gap-3 sm:grid-cols-3">
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Route</dt>
          <dd className="font-mono text-sm text-slate-200">{page.route_template}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Reached by</dt>
          <dd className="text-sm text-slate-200">
            {NAVIGATION_LABELS[page.navigation_kind]}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Seen as</dt>
          <dd className="text-sm text-slate-200">{page.authentication_state}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Depth</dt>
          <dd className="text-sm text-slate-200">{page.depth}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">HTTP status</dt>
          <dd className="text-sm text-slate-200">
            {page.status ?? (
              <span className="text-slate-500" title="A client-side route serves no document">
                —
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Came from</dt>
          <dd className="truncate font-mono text-xs text-slate-300">
            {page.source_page_url ?? "entry point"}
          </dd>
        </div>
      </dl>

      {page.error ? (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
          {page.error}
        </p>
      ) : null}

      <section>
        <h4 className="mb-2 text-sm font-semibold text-slate-200">
          Forms ({page.forms.length}) — read, never submitted
        </h4>
        {page.forms.length === 0 ? (
          <p className="text-sm text-slate-500">None on this page.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {page.forms.map((form, index) => (
              <div
                key={`${form.selector}-${index}`}
                className="rounded-lg border border-slate-800 bg-slate-950/40 p-3"
              >
                <p className="font-mono text-xs text-slate-400">
                  {form.method.toUpperCase()} {form.action || "(no action attribute)"}
                </p>
                <ul className="mt-2 flex flex-col gap-1">
                  {form.fields.map((field) => (
                    <li key={field.selector} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="text-slate-200">
                        {field.label || field.name || field.field_id || "(unnamed)"}
                      </span>
                      <span className="rounded border border-slate-700 px-1.5 text-xs text-slate-400">
                        {field.type}
                      </span>
                      {field.required ? (
                        <span className="text-xs text-sky-300">required</span>
                      ) : null}
                      {field.sensitive ? (
                        <span
                          className="text-xs text-amber-300"
                          title="A credential would go here. No value was collected."
                        >
                          sensitive
                        </span>
                      ) : null}
                      <span className="truncate font-mono text-xs text-slate-600">
                        {field.selector}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h4 className="mb-2 text-sm font-semibold text-slate-200">
          Interactive elements ({page.elements.length})
        </h4>
        {page.elements.length === 0 ? (
          <p className="text-sm text-slate-500">None found.</p>
        ) : (
          <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-900 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Kind</th>
                  <th className="px-3 py-2">Label</th>
                  <th className="px-3 py-2">Reference</th>
                  <th className="px-3 py-2">From</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {page.elements.map((element, index) => (
                  <tr key={`${element.selector}-${index}`} className="bg-slate-950/40">
                    <td className="px-3 py-1.5 text-slate-300">{element.kind}</td>
                    <td className="max-w-48 truncate px-3 py-1.5 text-slate-200">
                      {element.text || "—"}
                    </td>
                    <td className="max-w-64 truncate px-3 py-1.5 font-mono text-xs text-slate-400">
                      {element.selector}
                    </td>
                    <td className="px-3 py-1.5 text-xs text-slate-500">
                      {element.selector_strategy}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="flex justify-end">
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
