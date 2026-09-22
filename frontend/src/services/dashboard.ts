import { apiGet } from "@/services/api";
import type { Dashboard } from "@/types/dashboard";

/** One aggregated read of the stored assessments, issues and targets. */
export function getDashboard(
  { historyLimit = 20, trendDays = 30 }: { historyLimit?: number; trendDays?: number } = {},
  signal?: AbortSignal,
): Promise<Dashboard> {
  const params = new URLSearchParams({
    history_limit: String(historyLimit),
    trend_days: String(trendDays),
  });
  return apiGet<Dashboard>(`/dashboard?${params}`, { signal });
}
