/**
 * lib/posthog — thin, default-off product-analytics wrapper.
 *
 * Gated behind VITE_POSTHOG_KEY, absent by default (matching the
 * credential-presence-is-the-opt-in convention every other MarketOS
 * integration uses — e.g. FIRECRAWL_API_KEY in
 * backend/adapters/alibaba_trends.py). With no key configured, every
 * exported function is a no-op: nothing is captured, no network call is
 * made, and the rest of the app never has to check whether analytics is
 * enabled before calling these.
 */
import posthog from "posthog-js";

const KEY = import.meta.env.VITE_POSTHOG_KEY as string | undefined;
const HOST = (import.meta.env.VITE_POSTHOG_HOST as string) || "https://us.i.posthog.com";

let initialized = false;

export function initPosthog(): void {
  if (!KEY || initialized) return;
  posthog.init(KEY, {
    api_host: HOST,
    capture_pageview: false, // captured manually on route change, see usePosthogPageview
    autocapture: false,      // explicit events only — no blanket click/DOM capture
  });
  initialized = true;
}

export function capturePageview(path: string): void {
  if (!KEY || !initialized) return;
  posthog.capture("$pageview", { $current_url: path });
}

export function captureEvent(name: string, properties?: Record<string, unknown>): void {
  if (!KEY || !initialized) return;
  posthog.capture(name, properties);
}
