import { apiGet, apiPost } from "@/services/api";
import type {
  ApplicationMap,
  DiscoveryRun,
  DiscoveryStartRequest,
} from "@/types/discovery";

/**
 * Discovery is always addressed through the target it explores. There is no
 * route that reaches a map without naming the application it belongs to.
 */
const base = (targetId: string) => `/targets/${targetId}`;

export function listDiscoveries(
  targetId: string,
  signal?: AbortSignal,
): Promise<DiscoveryRun[]> {
  return apiGet<DiscoveryRun[]>(`${base(targetId)}/discoveries`, { signal });
}

export function getDiscovery(
  targetId: string,
  discoveryId: string,
  signal?: AbortSignal,
): Promise<ApplicationMap> {
  return apiGet<ApplicationMap>(`${base(targetId)}/discoveries/${discoveryId}`, { signal });
}

export function getApplicationMap(
  targetId: string,
  signal?: AbortSignal,
): Promise<ApplicationMap> {
  return apiGet<ApplicationMap>(`${base(targetId)}/application-map`, { signal });
}

/**
 * Run a real crawl and wait for it.
 *
 * This opens a browser on the server and walks the application, so it takes
 * as long as the crawl takes. Answering before the browser had finished
 * would say nothing about whether the target was reachable, which is the
 * question worth asking.
 */
export function startDiscovery(
  targetId: string,
  body: DiscoveryStartRequest = {},
): Promise<ApplicationMap> {
  return apiPost<ApplicationMap>(`${base(targetId)}/discoveries`, body, {
    acceptStatuses: [201],
  });
}
