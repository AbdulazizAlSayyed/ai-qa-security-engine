/**
 * Frontend runtime configuration.
 *
 * Everything the browser bundle needs comes from VITE_* variables, which Vite
 * inlines at build time. Nothing secret belongs here - this file ends up in
 * the shipped JavaScript.
 */

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function resolveApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  const value = configured && configured.length > 0 ? configured : DEFAULT_API_BASE_URL;
  // Trailing slashes would produce "//health" when paths are appended.
  return value.replace(/\/+$/, "");
}

export const config = {
  apiBaseUrl: resolveApiBaseUrl(),
  /** How often the dashboard re-checks backend health, in milliseconds. */
  healthPollIntervalMs: 15_000,
} as const;
