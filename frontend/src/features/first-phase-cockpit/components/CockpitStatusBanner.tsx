import type { EvidenceMode, EvidenceState } from "../contracts/firstPhaseEvidencePacket";

const STATE_STYLES: Record<EvidenceState, string> = {
  loading: "border-zinc-700 bg-zinc-900/40 text-zinc-400",
  empty: "border-zinc-700 bg-zinc-900/40 text-zinc-400",
  blocked: "border-red-500/30 bg-red-500/10 text-red-200",
  unavailable: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  stale: "border-orange-500/30 bg-orange-500/10 text-orange-200",
  partial: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
};

const STATE_HINTS: Record<EvidenceState, string> = {
  loading: "Fetching Phase 1 readiness, benchmark matrix, public market, and research portfolio…",
  empty: "No first-phase evidence is available yet. Waiting for backend packets or fixture data.",
  blocked: "Hard blockers prevent advancement. Review blocked reasons before any operator action.",
  unavailable: "Required Phase 1 endpoints are unavailable. Partial or empty evidence only.",
  stale: "Readiness reports degraded/stale evidence. Treat rankings as advisory and dated.",
  partial: "Some endpoints or readiness stages are incomplete. Review unavailable markers before acting.",
  success: "Evidence packet composed without fatal errors. This is not live validated. Ranking and launch authority remain server-side.",
};

const MODE_EXPLANATIONS: Record<EvidenceMode, string> = {
  fixture_only: "Fixture evidence is screening-only. It is not live validated, not live supplier proof, and not commercial validation.",
  manual: "Manual import is operator-supplied screening evidence. It does not authorize orders, spend, or launch.",
  simulated: "Simulated values are derived planning assumptions, not observed live results.",
  live_readonly: "Live-readonly means the backend reported a read-only live path. This cockpit still cannot mutate providers.",
  unknown: "Evidence mode is unknown. Treat every field as unavailable until provenance is explicit.",
};

export function CockpitStatusBanner({
  state,
  overallStatus,
  nextBestAction,
  evidenceMode,
  projectionWarning,
  unmatchedServerCount,
  unmatchedProjectionCount,
}: {
  state: EvidenceState;
  overallStatus: string | null;
  nextBestAction: string | null;
  evidenceMode: EvidenceMode | string | null;
  projectionWarning?: string | null;
  unmatchedServerCount?: number;
  unmatchedProjectionCount?: number;
}) {
  const modeKey = (evidenceMode ?? "unknown") as EvidenceMode;
  const explanation = MODE_EXPLANATIONS[modeKey] ?? MODE_EXPLANATIONS.unknown;
  return (
    <section
      className={`rounded-lg border p-4 ${STATE_STYLES[state]}`}
      aria-live="polite"
      aria-atomic="true"
      role="status"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-zinc-100">First-phase evidence review</h2>
          <p className="mt-1 text-xs text-zinc-400">{STATE_HINTS[state]}</p>
        </div>
        <span
          className="rounded border border-indigo-500/30 bg-indigo-500/10 px-2 py-1 text-[11px] text-indigo-200"
          aria-label={`Cockpit state ${state}`}
        >
          {state}
        </span>
      </div>
      <p className="mt-3 text-xs text-zinc-300">{explanation}</p>
      <p className="mt-1 text-[11px] text-zinc-400">
        Packet state is compose completeness, not live proof. Launch remains unauthorized in this cockpit.
      </p>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {overallStatus && (
          <p>
            Overall status: <span className="font-medium">{overallStatus.replace(/_/g, " ")}</span>
          </p>
        )}
        {evidenceMode && (
          <p>
            Evidence mode: <span className="font-medium">{String(evidenceMode).replace(/_/g, " ")}</span>
          </p>
        )}
        {nextBestAction && (
          <p>
            Next best action: <span className="font-medium">{nextBestAction.replace(/_/g, " ")}</span>
          </p>
        )}
      </div>
      {(projectionWarning || unmatchedServerCount || unmatchedProjectionCount) && (
        <p className="mt-2 text-[11px] text-amber-200">
          {projectionWarning ? `Projection: ${projectionWarning.replace(/_/g, " ")}. ` : ""}
          {unmatchedServerCount ? `${unmatchedServerCount} server row(s) have no matching report. ` : ""}
          {unmatchedProjectionCount ? `${unmatchedProjectionCount} report row(s) have no matching server rank. ` : ""}
          Unmatched report rows are not inserted and never re-rank the table.
        </p>
      )}
    </section>
  );
}
