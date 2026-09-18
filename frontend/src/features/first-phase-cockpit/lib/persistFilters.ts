import type { CandidateFilterState } from "../contracts/firstPhaseEvidencePacket";
import { DEFAULT_CANDIDATE_FILTER } from "./filterCandidates";

export const FILTER_STORAGE_KEY = "marketos.first-phase-cockpit.filters";

function asFilter(raw: Partial<CandidateFilterState> | null | undefined): CandidateFilterState {
  return {
    query: typeof raw?.query === "string" ? raw.query.slice(0, 120) : DEFAULT_CANDIDATE_FILTER.query,
    risk:
      raw?.risk === "all"
      || raw?.risk === "high"
      || raw?.risk === "medium"
      || raw?.risk === "low"
      || raw?.risk === "unknown"
        ? raw.risk
        : DEFAULT_CANDIDATE_FILTER.risk,
    decision: typeof raw?.decision === "string" && raw.decision ? raw.decision.slice(0, 80) : DEFAULT_CANDIDATE_FILTER.decision,
    topOnly: Boolean(raw?.topOnly),
    topN: Boolean(raw?.topN),
  };
}

export function parseFilterSearch(search: string): CandidateFilterState | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  if (![...params.keys()].some((key) => ["q", "risk", "decision", "top", "topn"].includes(key))) {
    return null;
  }
  return asFilter({
    query: params.get("q") ?? "",
    risk: (params.get("risk") ?? "all") as CandidateFilterState["risk"],
    decision: params.get("decision") ?? "all",
    topOnly: params.get("top") === "1",
    topN: params.get("topn") === "1",
  });
}

export function serializeFilterSearch(filter: CandidateFilterState): string {
  const params = new URLSearchParams();
  if (filter.query.trim()) params.set("q", filter.query.trim());
  if (filter.risk !== "all") params.set("risk", filter.risk);
  if (filter.decision !== "all") params.set("decision", filter.decision);
  if (filter.topOnly) params.set("top", "1");
  if (filter.topN) params.set("topn", "1");
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function readStoredFilter(): CandidateFilterState | null {
  if (typeof sessionStorage === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(FILTER_STORAGE_KEY);
    if (!raw) return null;
    return asFilter(JSON.parse(raw) as Partial<CandidateFilterState>);
  } catch {
    return null;
  }
}

export function writeStoredFilter(filter: CandidateFilterState): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(asFilter(filter)));
  } catch {
    // Storage may be blocked; keep in-memory filter only.
  }
}

export function initialFilter(search: string): CandidateFilterState {
  return parseFilterSearch(search) ?? readStoredFilter() ?? DEFAULT_CANDIDATE_FILTER;
}
