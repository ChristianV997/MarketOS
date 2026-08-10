// Centralized, explicit, privacy-safe browser analytics events.
import { captureEvent } from "./posthog";

const ALLOWED_EVENTS = new Set([
  "operator_event_dashboard_viewed",
  "operator_event_source_changed",
  "operator_event_filters_applied",
  "operator_event_refresh_clicked",
  "public_commerce_run_started",
  "public_commerce_run_succeeded",
  "public_commerce_run_blocked",
  "public_commerce_run_degraded",
  "public_commerce_run_stale_cache",
]);

const ALLOWED_PROPERTIES = new Set([
  "source", "max_signals", "max_candidates", "event_target", "status", "event_count",
  "signal_count", "candidate_count", "query_length", "limit", "read_only", "advisory",
]);

export function analyticsEnabled(): boolean {
  return Boolean(import.meta.env.VITE_POSTHOG_KEY);
}

export function sanitizeAnalyticsProperties(properties: Record<string, unknown> = {}): Record<string, unknown> {
  const safe: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(properties)) {
    if (!ALLOWED_PROPERTIES.has(key)) continue;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") safe[key] = value;
  }
  return safe;
}

export function trackSafeEvent(name: string, properties: Record<string, unknown> = {}): void {
  if (!ALLOWED_EVENTS.has(name)) return;
  captureEvent(name, sanitizeAnalyticsProperties(properties));
}
