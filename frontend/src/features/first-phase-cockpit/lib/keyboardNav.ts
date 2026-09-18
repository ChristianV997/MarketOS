/** Roving-index helpers for the ranked-candidate grid. Does not reorder rows. */

export function adjacentCandidateIndex(
  length: number,
  currentIndex: number,
  key: string,
): number {
  if (length <= 0) return -1;
  const current = Math.min(Math.max(0, currentIndex), length - 1);
  if (key === "Home") return 0;
  if (key === "End") return length - 1;
  if (key === "ArrowDown") return Math.min(current + 1, length - 1);
  if (key === "ArrowUp") return Math.max(current - 1, 0);
  return current;
}

export function shouldHandoffDetailFocus(key: string): boolean {
  return key === "Enter" || key === " ";
}
