import {
  CANDIDATE_WINDOW_SIZE,
  type RankedCandidateRow,
} from "../contracts/firstPhaseEvidencePacket.ts";

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

/**
 * Window start for the next render. The selection pulls the window only when the selection or the candidate
 * list changes. Paging with Previous/Next moves the window alone, so a selection that is outside the new
 * window must not undo the page.
 */
export function windowStartAfterChange(
  candidates: RankedCandidateRow[],
  selectedId: string | null,
  windowStart: number,
  previous: { candidates: RankedCandidateRow[]; selectedId: string | null } | null,
  windowSize: number = CANDIDATE_WINDOW_SIZE,
): number {
  if (previous && previous.candidates === candidates && previous.selectedId === selectedId) return windowStart;
  return ensureSelectionInWindow(candidates, selectedId, windowStart, windowSize);
}
