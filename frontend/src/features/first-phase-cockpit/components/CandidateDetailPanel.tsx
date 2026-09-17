import type { RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket";

export function CandidateDetailPanel({
  candidate,
  onClear,
}: {
  candidate: RankedCandidateRow | null;
  onClear: () => void;
}) {
  if (!candidate) {
    return (
      <section
        className="rounded-lg border border-dashed border-zinc-700 bg-zinc-900/20 p-4 text-sm text-zinc-500"
        aria-label="Candidate detail empty"
      >
        Select a candidate row to inspect pillar-level evidence, provenance, and next action. Detail view is read-only.
      </section>
    );
  }

  return (
    <section
      id="candidate-detail-panel"
      tabIndex={-1}
      className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-4 outline-none focus-visible:ring-1 focus-visible:ring-indigo-400"
      aria-label={`Candidate detail ${candidate.title}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-zinc-100">{candidate.title}</h3>
          <p className="mt-1 text-[11px] text-zinc-500">
            Rank {candidate.rankIndex + 1}
            {candidate.isTopCandidate ? " · top candidate" : ""} · {candidate.candidateId}
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-300 hover:border-zinc-500"
        >
          Clear selection
        </button>
      </div>

      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Commercial decision</dt>
          <dd className="mt-1 text-zinc-200">{candidate.commercialDecision?.replace(/_/g, " ") ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Next best action</dt>
          <dd className="mt-1 text-zinc-200">{candidate.nextBestAction?.replace(/_/g, " ") ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Evidence mode</dt>
          <dd className="mt-1 text-zinc-200">{candidate.evidenceMode.replace(/_/g, " ")}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Evidence class</dt>
          <dd className="mt-1 text-zinc-200">{candidate.evidenceClass.replace(/_/g, " ")}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Source family</dt>
          <dd className="mt-1 text-zinc-200">{candidate.sourceFamily?.replace(/_/g, " ") ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Risk</dt>
          <dd className="mt-1 text-zinc-200">{candidate.riskLevel ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Validation priority</dt>
          <dd className="mt-1 text-zinc-200">
            {(candidate.validationPriority ?? "—").replace(/_/g, " ")}
            {candidate.validationTarget ? ` → ${candidate.validationTarget}` : ""}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Assumption ratio</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.assumptionRatio !== null
              ? `${(candidate.assumptionRatio * 100).toFixed(0)}%`
              : "—"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-500">Evidence completeness</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.evidenceCompleteness !== null
              ? `${(candidate.evidenceCompleteness * 100).toFixed(0)}%`
              : "—"}
          </dd>
        </div>
      </dl>

      <h4 className="mt-4 text-xs font-medium text-zinc-300">Pillar-level evidence</h4>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {candidate.pillarCells.map((cell) => (
          <li key={cell.pillarId} className="rounded border border-zinc-800 bg-zinc-950/40 p-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="text-zinc-200">{cell.label}</span>
              <span className="text-[10px] text-zinc-500">{cell.status} · {cell.evidenceClass.replace(/_/g, " ")}</span>
            </div>
            <p className="mt-1 text-zinc-400">
              {cell.score !== null ? `${(cell.score * 100).toFixed(0)}%` : "—"}
              {cell.detail ? ` · ${cell.detail.replace(/_/g, " ")}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
