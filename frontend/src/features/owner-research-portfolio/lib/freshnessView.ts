import { formatFreshnessLabel, isStaleFreshness } from "../../first-phase-cockpit/lib/freshness";
import type { FreshnessView } from "../contracts/ownerResearch";

export const FRESHNESS_NOT_REPORTED: FreshnessView = Object.freeze({
  status: "not_reported",
  label: "Freshness not reported",
  expiresAt: null,
});

function humanAge(label: string): string {
  if (label === "fresh_<1m") return "under 1 minute ago";
  const match = /^age_(\d+)([mhd])$/.exec(label);
  if (!match) return label;
  const unit = match[2] === "m" ? "min" : match[2] === "h" ? "h" : "d";
  return `${match[1]} ${unit} ago`;
}

/**
 * Deterministic freshness description. Reuses the cockpit's age/stale helpers
 * (24h default stale threshold) and never invents a timestamp: with neither an
 * expiry nor a generation time the result is `not_reported`.
 */
export function describeFreshness(input: {
  expiresAt?: string | null;
  generatedAt?: string | null;
  nowMs: number;
}): FreshnessView {
  const { expiresAt, generatedAt, nowMs } = input;

  if (expiresAt) {
    const expiry = Date.parse(expiresAt);
    if (Number.isNaN(expiry)) {
      return { status: "invalid", label: "Freshness expiry is not a valid date", expiresAt: null };
    }
    return nowMs > expiry
      ? { status: "stale", label: `Expired ${expiresAt}`, expiresAt }
      : { status: "fresh", label: `Fresh until ${expiresAt}`, expiresAt };
  }

  if (generatedAt) {
    const ageLabel = formatFreshnessLabel(generatedAt, nowMs);
    if (ageLabel === null || ageLabel === "freshness_unavailable") {
      return { status: "invalid", label: "Generation time is not a valid date", expiresAt: null };
    }
    return isStaleFreshness(ageLabel)
      ? { status: "stale", label: `Generated ${humanAge(ageLabel)} (stale after 24h)`, expiresAt: null }
      : { status: "fresh", label: `Generated ${humanAge(ageLabel)}; no expiry reported`, expiresAt: null };
  }

  return FRESHNESS_NOT_REPORTED;
}
