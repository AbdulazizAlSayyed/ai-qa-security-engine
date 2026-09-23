import { NavLink, Outlet } from "react-router-dom";

import { config } from "@/lib/config";

interface NavItem {
  label: string;
  to: string;
}

const NAV: NavItem[] = [
  { label: "Dashboard", to: "/" },
  { label: "Targets", to: "/targets" },
  { label: "Requirements", to: "/requirements" },
  { label: "QA Engine", to: "/qa" },
  { label: "Security", to: "/security" },
  { label: "Assessments", to: "/assessments" },
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
            {NAV.map((item) => (
              <li key={item.label}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
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
            ))}
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
