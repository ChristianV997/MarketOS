import type { EvidenceState } from "../contracts/firstPhaseEvidencePacket";

const STATE_STYLES: Record<EvidenceState, string> = {
  loading: "border-zinc-700 bg-zinc-900/40 text-zinc-400",
  empty: "border-zinc-700 bg-zinc-900/40 text-zinc-400",
  blocked: "border-red-500/30 bg-red-500/10 text-red-200",
  unavailable: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  stale: "border-orange-500/30 bg-orange-500/10 text-orange-200",
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
};

export function CockpitStatusBanner({
  state,
  overallStatus,
  nextBestAction,
}: {
  state: EvidenceState;
  overallStatus: string | null;
  nextBestAction: string | null;
}) {
  return (
    <section className={`rounded-lg border p-4 ${STATE_STYLES[state]}`} aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-zinc-100">First-phase evidence review</h2>
          <p className="mt-1 text-xs text-zinc-400">
            Read-only decision cockpit. Ranking and launch authority remain server-side.
          </p>
        </div>
        <span className="rounded border border-indigo-500/30 bg-indigo-500/10 px-2 py-1 text-[11px] text-indigo-200">
          {state}
        </span>
      </div>
      {overallStatus && (
        <p className="mt-3 text-xs">
          Overall status: <span className="font-medium">{overallStatus.replace(/_/g, " ")}</span>
        </p>
      )}
      {nextBestAction && (
        <p className="mt-1 text-xs">
          Next best action: <span className="font-medium">{nextBestAction.replace(/_/g, " ")}</span>
        </p>
      )}
    </section>
  );
}
