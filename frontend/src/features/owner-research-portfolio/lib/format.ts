/** Display helpers. A missing value is always "Not reported", never zero. */

export const NOT_REPORTED = "Not reported";

export function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Backend scores/completeness are 0-1 fractions in the canonical packet. Show a
 * percentage only inside that range; anything else is shown raw and flagged so a
 * scale change is visible instead of silently mis-rendered.
 */
export function formatReportedScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NOT_REPORTED;
  if (value >= 0 && value <= 1) return `${Math.round(value * 100)}%`;
  return `${value} (outside 0-1)`;
}

export function humanize(token: string | null | undefined): string {
  if (!token) return NOT_REPORTED;
  return token.replace(/[_-]+/g, " ").trim() || NOT_REPORTED;
}

export function uniqueStrings(values: readonly unknown[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    out.push(trimmed);
  }
  return out;
}

export function stringList(value: unknown): string[] {
  return Array.isArray(value) ? uniqueStrings(value) : [];
}
