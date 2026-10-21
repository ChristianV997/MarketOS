export const MAX_COMPARISON_CANDIDATES = 3;

/** Toggle a canonical candidate ID without mutating the current selection. */
export function toggleComparisonCandidate(
  candidateIds: readonly string[],
  candidateId: string,
): string[] {
  if (candidateIds.includes(candidateId)) {
    return candidateIds.filter((id) => id !== candidateId);
  }
  if (candidateIds.length >= MAX_COMPARISON_CANDIDATES) return [...candidateIds];
  return [...candidateIds, candidateId];
}
