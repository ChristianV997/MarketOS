import {
  CANDIDATE_WINDOW_SIZE,
  type RankedCandidateRow,
} from "../contracts/firstPhaseEvidencePacket";

export interface CandidateWindow {
  visible: RankedCandidateRow[];
  windowStart: number;
  windowSize: number;
  total: number;
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
}

/**
 * Slice a ranked list into a bounded window without reordering.
 * Pattern adapted from TanStack virtualization concepts without adding a dependency.
 */
export function windowCandidates(
  candidates: RankedCandidateRow[],
  windowStart: number,
  windowSize: number = CANDIDATE_WINDOW_SIZE,
): CandidateWindow {
  const size = Math.max(1, windowSize);
  const start = Math.max(0, Math.min(windowStart, Math.max(0, candidates.length - 1)));
  const clampedStart = candidates.length === 0 ? 0 : Math.min(start, Math.max(0, candidates.length - size));
  const visible = candidates.slice(clampedStart, clampedStart + size);
  return {
    visible,
    windowStart: clampedStart,
    windowSize: size,
    total: candidates.length,
    hasMoreBefore: clampedStart > 0,
    hasMoreAfter: clampedStart + size < candidates.length,
  };
}

export function nextWindowStart(current: CandidateWindow, direction: "forward" | "back"): number {
  if (direction === "forward") {
    return Math.min(current.windowStart + current.windowSize, Math.max(0, current.total - current.windowSize));
  }
  return Math.max(0, current.windowStart - current.windowSize);
}

/** Ensure selected row is brought into the visible window without changing order. */
export function ensureSelectionInWindow(
  candidates: RankedCandidateRow[],
  selectedId: string | null,
  windowStart: number,
  windowSize: number = CANDIDATE_WINDOW_SIZE,
): number {
  if (!selectedId || candidates.length === 0) return windowStart;
  const index = candidates.findIndex((candidate) => candidate.candidateId === selectedId);
  if (index < 0) return windowStart;
  if (index < windowStart) return index;
  if (index >= windowStart + windowSize) return Math.max(0, index - windowSize + 1);
  return windowStart;
}
