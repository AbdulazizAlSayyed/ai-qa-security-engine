import { useCallback, useEffect, useRef, useState } from "react";

import { config } from "@/lib/config";
import { fetchHealth } from "@/services/health";
import type { HealthResponse } from "@/types/health";

export interface UseHealthResult {
  health: HealthResponse | null;
  /** Set only when the backend could not be reached or parsed at all. */
  error: string | null;
  isChecking: boolean;
  lastCheckedAt: Date | null;
  refresh: () => void;
}

/**
 * Poll the backend's /health endpoint.
 *
 * A degraded backend (503) is not an error here: it resolves to a health
 * object whose database.status is "unavailable", which the dashboard renders
 * as a failed hop rather than a dead connection.
 */
export function useHealth(): UseHealthResult {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(true);
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);

  const inFlight = useRef<AbortController | null>(null);

  const check = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setIsChecking(true);
    try {
      const result = await fetchHealth(controller.signal);
      if (controller.signal.aborted) return;
      setHealth(result);
      setError(null);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setHealth(null);
      setError(caught instanceof Error ? caught.message : "Unexpected error");
    } finally {
      if (!controller.signal.aborted) {
        setIsChecking(false);
        setLastCheckedAt(new Date());
      }
    }
  }, []);

  useEffect(() => {
    void check();
    const timer = window.setInterval(() => {
      void check();
    }, config.healthPollIntervalMs);

    return () => {
      window.clearInterval(timer);
      inFlight.current?.abort();
    };
  }, [check]);

  const refresh = useCallback(() => {
    void check();
  }, [check]);

  return { health, error, isChecking, lastCheckedAt, refresh };
}
