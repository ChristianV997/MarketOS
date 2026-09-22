import { useMemo } from "react";
import type { CandidateFilterState, RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket";
import { STABLE_TOP_N } from "../contracts/firstPhaseEvidencePacket";
import { uniqueDecisions } from "../lib/filterCandidates";

export function CockpitToolbar({
  filter,
  candidates,
  filteredCount,
  onFilterChange,
  onExport,
  exportDisabled,
}: {
  filter: CandidateFilterState;
  candidates: RankedCandidateRow[];
  filteredCount: number;
  onFilterChange: (next: CandidateFilterState) => void;
  onExport: () => void;
  exportDisabled: boolean;
}) {
  const decisions = useMemo(() => uniqueDecisions(candidates), [candidates]);

  return (
    <section
      className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4"
      aria-label="Cockpit filters and export"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid flex-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block text-xs text-zinc-400">
            Search candidates
            <input
              type="search"
              value={filter.query}
              onChange={(event) => onFilterChange({ ...filter, query: event.target.value })}
              placeholder="Title, decision, action…"
              className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-400 focus:border-indigo-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
              aria-controls="ranked-candidates-table"
            />
          </label>
          <label className="block text-xs text-zinc-400">
            Risk
            <select
              value={filter.risk}
              onChange={(event) =>
                onFilterChange({
                  ...filter,
                  risk: event.target.value as CandidateFilterState["risk"],
                })
              }
              className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
            >
              <option value="all">All risks</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
          <label className="block text-xs text-zinc-400">
            Decision
            <select
              value={filter.decision}
              onChange={(event) => onFilterChange({ ...filter, decision: event.target.value })}
              className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
            >
              <option value="all">All decisions</option>
              {decisions.map((decision) => (
                <option key={decision} value={decision}>
                  {decision.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 pt-5 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={filter.topN}
              onChange={(event) => onFilterChange({ ...filter, topN: event.target.checked })}
              className="rounded border-zinc-600"
            />
            Stable top {STABLE_TOP_N} (server order)
          </label>
          <label className="flex items-center gap-2 pt-5 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={filter.topOnly}
              onChange={(event) => onFilterChange({ ...filter, topOnly: event.target.checked })}
              className="rounded border-zinc-600"
            />
            Top candidate only
          </label>
        </div>
        <button
          type="button"
          onClick={onExport}
          disabled={exportDisabled}
          className="min-h-8 rounded border border-zinc-600 bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-200 enabled:hover:border-indigo-500 enabled:hover:text-indigo-200 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          Export client-safe JSON
        </button>
      </div>
      <p className="mt-3 text-[11px] text-zinc-400" aria-live="polite">
        Showing {filteredCount} of {candidates.length} candidates · server order preserved · filters never re-rank
      </p>
    </section>
  );
}
