import { Route, Routes } from "react-router-dom";

import AppLayout from "@/layouts/AppLayout";
import AssessmentDetailPage from "@/pages/AssessmentDetailPage";
import AssessmentsPage from "@/pages/AssessmentsPage";
import DashboardPage from "@/pages/DashboardPage";
import NotFoundPage from "@/pages/NotFoundPage";
import QaPage from "@/pages/QaPage";
import SecurityPage from "@/pages/SecurityPage";
import TargetsPage from "@/pages/TargetsPage";

/**
 * Route table.
 *
 * Dashboard (Phase 0, aggregated overview since Phase 7), Targets (Phase 1),
 * QA (Phase 2), Security (Phase 3) and Assessments (Phase 4; AI analysis and
 * prioritized issues live on the detail page) exist. Findings and Reports arrive with the
 * phases that actually build them - they are shown in the sidebar as
 * disabled rather than routed to empty placeholder pages.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/targets" element={<TargetsPage />} />
        <Route path="/qa" element={<QaPage />} />
        <Route path="/security" element={<SecurityPage />} />
        <Route path="/assessments" element={<AssessmentsPage />} />
        <Route path="/assessments/:id" element={<AssessmentDetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
