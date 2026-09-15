import { Route, Routes } from "react-router-dom";

import AppLayout from "@/layouts/AppLayout";
import DashboardPage from "@/pages/DashboardPage";
import NotFoundPage from "@/pages/NotFoundPage";

/**
 * Route table.
 *
 * Only the dashboard exists in Phase 0. Targets, Assessments, Findings and
 * Reports arrive with the phases that actually build them - they are shown
 * in the sidebar as disabled rather than routed to empty placeholder pages.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
