import type { EvidenceState } from "../contracts/firstPhaseEvidencePacket";

const STATE_STYLES: Record<EvidenceState, string> = {
  loading: "border-zinc-700 bg-zinc-900/40 text-zinc-400",
  empty: "border-zinc-700 bg-zinc-900/40 text-zinc-400",
  blocked: "border-red-500/30 bg-red-500/10 text-red-200",
  unavailable: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  stale: "border-orange-500/30 bg-orange-500/10 text-orange-200",
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
};

const STATE_HINTS: Record<EvidenceState, string> = {
  loading: "Fetching Phase 1 readiness, benchmark matrix, public market, and research portfolio…",
  empty: "No first-phase evidence is available yet. Waiting for backend packets or fixture data.",
  blocked: "Hard blockers prevent advancement. Review blocked reasons before any operator action.",
  unavailable: "Required Phase 1 endpoints are unavailable. Partial or empty evidence only.",
  stale: "Readiness reports degraded/stale evidence. Treat rankings as advisory and dated.",
  success: "Evidence packet composed successfully. Ranking and launch authority remain server-side.",
};

export function CockpitStatusBanner({
  state,
  overallStatus,
  nextBestAction,
  evidenceMode,
}: {
  state: EvidenceState;
  overallStatus: string | null;
  nextBestAction: string | null;
  evidenceMode: string | null;
}) {
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
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {overallStatus && (
          <p>
            Overall status: <span className="font-medium">{overallStatus.replace(/_/g, " ")}</span>
          </p>
        )}
        {evidenceMode && (
          <p>
            Evidence mode: <span className="font-medium">{evidenceMode.replace(/_/g, " ")}</span>
          </p>
        )}
        {nextBestAction && (
          <p>
            Next best action: <span className="font-medium">{nextBestAction.replace(/_/g, " ")}</span>
          </p>
        )}
      </div>
    </section>
  );
}
