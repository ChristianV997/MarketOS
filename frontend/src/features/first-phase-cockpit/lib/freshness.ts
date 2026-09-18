/**
 * Deterministic freshness / age labels for run metadata.
 * Never invents timestamps — returns null when generatedAt is missing/invalid.
 */

export function formatFreshnessLabel(
  generatedAt: string | null | undefined,
  nowMs: number,
): string | null {
  if (!generatedAt) return null;
  const parsed = Date.parse(generatedAt);
  if (Number.isNaN(parsed)) return "freshness_unavailable";
  const ageMs = Math.max(0, nowMs - parsed);
  const ageMinutes = Math.floor(ageMs / 60_000);
  if (ageMinutes < 1) return "fresh_<1m";
  if (ageMinutes < 60) return `age_${ageMinutes}m`;
  const ageHours = Math.floor(ageMinutes / 60);
  if (ageHours < 48) return `age_${ageHours}h`;
  const ageDays = Math.floor(ageHours / 24);
  return `age_${ageDays}d`;
}

export function isStaleFreshness(label: string | null, staleAfterHours = 24): boolean {
  if (!label || label === "freshness_unavailable") return false;
  if (label.startsWith("age_") && label.endsWith("d")) {
    const days = Number(label.slice(4, -1));
    return Number.isFinite(days) && days * 24 >= staleAfterHours;
  }
  if (label.startsWith("age_") && label.endsWith("h")) {
    const hours = Number(label.slice(4, -1));
    return Number.isFinite(hours) && hours >= staleAfterHours;
  }
  return false;
}
