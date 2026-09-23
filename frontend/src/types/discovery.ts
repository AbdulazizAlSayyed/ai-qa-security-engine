/**
 * Mirrors backend/app/schemas/discovery.py. Keep the two in step -
 * tests/test_frontend_contract.py fails when they drift.
 *
 * There is no field here for a credential, a cookie, a header, an input's
 * value or page HTML, and there should never be one: the discovery engine
 * never collects any of them, so the map has nothing of the sort to carry.
 */

export const DISCOVERY_STATUSES = ["created", "running", "completed", "failed"] as const;
export type DiscoveryStatus = (typeof DISCOVERY_STATUSES)[number];

export const STATUS_LABELS: Record<DiscoveryStatus, string> = {
  created: "Created",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
};

export type AuthenticationState = "anonymous" | "authenticated";

/** How the crawler reached a page. `click_client_side` means a router did it. */
export type NavigationKind = "goto" | "click_client_side" | "click_full_load";

export const NAVIGATION_LABELS: Record<NavigationKind, string> = {
  goto: "Opened directly",
  click_client_side: "Clicked (client-side route)",
  click_full_load: "Clicked (full page load)",
};

export interface DiscoveryLimits {
  max_pages: number;
  max_depth: number;
  max_navigations: number;
  max_duration_seconds: number;
  stabilize_ms: number;
  navigation_timeout_ms: number;
  max_links_per_page: number;
  max_elements_per_page: number;
  max_forms_per_page: number;
}

export interface DiscoveryAuthentication {
  attempted: boolean;
  succeeded: boolean;
  mode: string;
  /** The test account's name. Never a username's password. */
  account_name: string;
  reason: string;
  state: AuthenticationState;
}

export interface DiscoverySummary {
  pages: number;
  links: number;
  internal_links: number;
  external_links: number;
  forms: number;
  fields: number;
  elements: number;
  redirects: number;
  authentication_required_routes: number;
  blocked: number;
  client_side_navigations: number;
  routes: number;
}

export interface DiscoveredField {
  name: string;
  field_id: string;
  type: string;
  label: string;
  placeholder: string;
  required: boolean;
  selector: string;
  selector_strategy: string;
  input_mode: string;
  autocomplete: string;
  /** Marks a field a credential would go in. No value is ever collected. */
  sensitive: boolean;
}

export interface DiscoveredForm {
  page_url: string;
  form_id: string;
  name: string;
  action: string;
  method: string;
  selector: string;
  field_count: number;
  fields: DiscoveredField[];
}

export interface DiscoveredElement {
  page_url: string;
  kind: string;
  text: string;
  element_id: string;
  name: string;
  selector: string;
  selector_strategy: string;
  role: string;
  disabled: boolean;
  in_form: boolean;
}

export interface DiscoveredLink {
  source_page_url: string;
  href: string;
  url: string;
  path: string;
  text: string;
  internal: boolean;
  followed: boolean;
  navigation_kind: NavigationKind | null;
}

export interface DiscoveredRedirect {
  requested_url: string;
  requested_path: string;
  final_url: string;
  final_path: string;
  authentication_state: AuthenticationState;
  authentication_required: boolean;
  status: number | null;
}

export interface DiscoveredPage {
  url: string;
  path: string;
  route_template: string;
  title: string;
  depth: number;
  authentication_state: AuthenticationState;
  navigation_kind: NavigationKind;
  source_page_url: string | null;
  status: number | null;
  link_count: number;
  form_count: number;
  element_count: number;
  forms: DiscoveredForm[];
  elements: DiscoveredElement[];
  error: string | null;
}

export interface BlockedAddress {
  url: string;
  path: string;
  depth: number;
  source_page_url: string | null;
  reason: string;
}

/** One run without its map — what the list endpoint returns. */
export interface DiscoveryRun {
  id: string;
  target_id: string;
  target_name: string;
  target_base_url: string;
  discovery_id: string;
  status: DiscoveryStatus;
  base_url: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  discovery_version: string;
  limits: DiscoveryLimits;
  authentication: DiscoveryAuthentication;
  summary: DiscoverySummary;
  notes: string[];
  metadata: Record<string, unknown>;
  error: string | null;
}

/**
 * One run with everything it found.
 *
 * Written flat rather than `extends DiscoveryRun`: the backend contract test
 * compares this interface's own body against the full response model, and an
 * inherited field would look like a missing one.
 */
export interface ApplicationMap {
  id: string;
  target_id: string;
  target_name: string;
  target_base_url: string;
  discovery_id: string;
  status: DiscoveryStatus;
  base_url: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  discovery_version: string;
  limits: DiscoveryLimits;
  authentication: DiscoveryAuthentication;
  summary: DiscoverySummary;
  notes: string[];
  metadata: Record<string, unknown>;
  error: string | null;
  pages: DiscoveredPage[];
  links: DiscoveredLink[];
  redirects: DiscoveredRedirect[];
  blocked: BlockedAddress[];
}

/** Body for POST /targets/{target_id}/discoveries. An empty object is valid. */
export interface DiscoveryStartRequest {
  authenticated?: boolean;
  max_pages?: number;
  max_depth?: number;
  max_duration_seconds?: number;
}
