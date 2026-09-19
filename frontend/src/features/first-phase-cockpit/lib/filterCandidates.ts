import {
  STABLE_TOP_N,
  type CandidateFilterState,
  type RankedCandidateRow,
} from "../contracts/firstPhaseEvidencePacket.ts";

export const DEFAULT_CANDIDATE_FILTER: CandidateFilterState = {
  query: "",
  risk: "all",
  decision: "all",
  topOnly: false,
  topN: false,
};

/**
 * Filter candidates without changing relative order.
 * Never sorts — preserves backend rankIndex order.
 */
export function filterCandidates(
  candidates: RankedCandidateRow[],
  filter: CandidateFilterState,
): RankedCandidateRow[] {
  const query = filter.query.trim().toLowerCase();
  const filtered: RankedCandidateRow[] = [];
  for (const candidate of candidates) {
    if (filter.topN && candidate.rankIndex >= STABLE_TOP_N) continue;
    if (filter.topOnly && !candidate.isTopCandidate) continue;
    if (filter.risk !== "all") {
      const risk = (candidate.riskLevel ?? "unknown").toLowerCase();
      if (risk !== filter.risk) continue;
    }
    if (filter.decision !== "all") {
      if ((candidate.commercialDecision ?? "") !== filter.decision) continue;
    }
    if (query) {
      const haystack = [
        candidate.candidateId,
        candidate.title,
        candidate.sku,
        candidate.commercialDecision,
        candidate.nextBestAction,
        candidate.riskLevel,
        candidate.promotionState,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) continue;
    }
    filtered.push(candidate);
  }
  return filtered;
}

export function uniqueDecisions(candidates: RankedCandidateRow[]): string[] {
  const seen = new Set<string>();
  const decisions: string[] = [];
  for (const candidate of candidates) {
    if (!candidate.commercialDecision) continue;
    if (seen.has(candidate.commercialDecision)) continue;
    seen.add(candidate.commercialDecision);
    decisions.push(candidate.commercialDecision);
  }
  return decisions;
}
