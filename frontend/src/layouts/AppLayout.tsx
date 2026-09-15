import { NavLink, Outlet } from "react-router-dom";

import { config } from "@/lib/config";

interface NavItem {
  label: string;
  to?: string;
  phase?: string;
}

const NAV: NavItem[] = [
  { label: "Dashboard", to: "/" },
  { label: "Targets", phase: "Phase 1" },
  { label: "Assessments", phase: "Phase 2" },
  { label: "Findings", phase: "Phase 5" },
  { label: "Reports", phase: "Phase 10" },
];

export default function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <aside className="border-b border-slate-800 bg-slate-900/50 lg:w-64 lg:shrink-0 lg:border-r lg:border-b-0">
        <div className="px-6 py-5">
          <p className="text-sm font-semibold text-slate-100">AI QA &amp; Security</p>
          <p className="text-xs text-slate-500">Engine console</p>
        </div>

        <nav className="px-3 pb-5">
          <ul className="flex flex-wrap gap-1 lg:flex-col">
            {NAV.map((item) =>
              item.to ? (
                <li key={item.label}>
                  <NavLink
                    to={item.to}
                    end
                    className={({ isActive }) =>
                      `block rounded-lg px-3 py-2 text-sm transition-colors ${
                        isActive
                          ? "bg-sky-500/10 text-sky-300"
                          : "text-slate-300 hover:bg-slate-800/60 hover:text-slate-100"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ) : (
                <li
                  key={item.label}
                  className="flex items-center justify-between rounded-lg px-3 py-2 text-sm text-slate-600"
                  title={`Arrives in ${item.phase}`}
                >
                  <span>{item.label}</span>
                  <span className="font-mono text-[10px] text-slate-700">{item.phase}</span>
                </li>
              ),
            )}
          </ul>
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <main className="flex-1 px-6 py-8 lg:px-10">
          <Outlet />
        </main>

        <footer className="border-t border-slate-800 px-6 py-4 text-xs text-slate-600 lg:px-10">
          API base: <span className="font-mono">{config.apiBaseUrl}</span>
        </footer>
      </div>
    </div>
  );
}
