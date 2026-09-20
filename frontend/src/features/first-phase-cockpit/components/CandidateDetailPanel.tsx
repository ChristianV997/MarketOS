import type { RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket";
import { CommercialReviewTags, DecisionTimelinePanel, NextActionWorkflowPanel } from "./DecisionReviewPanels";

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
        className="rounded-lg border border-dashed border-zinc-700 bg-zinc-900/20 p-4 text-sm text-zinc-400"
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
          <p className="mt-1 text-[11px] text-zinc-400">
            Rank {candidate.rankIndex + 1}
            {candidate.isTopCandidate ? " · top candidate" : ""} · {candidate.candidateId}
            {candidate.sku ? ` · SKU ${candidate.sku}` : " · SKU unavailable"}
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="min-h-8 rounded border border-zinc-700 px-3 py-2 text-[11px] text-zinc-300 hover:border-zinc-500 focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          Clear selection
        </button>
      </div>

      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Exact SKU</dt>
          <dd className="mt-1 font-mono text-zinc-200">{candidate.sku ?? "unavailable from current endpoints"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Market lane</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.marketLane
              ? `${candidate.marketLane.origin ?? "—"} → ${candidate.marketLane.destination ?? "—"} (${candidate.marketLane.currency ?? "—"})`
              : "unavailable from current endpoints"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Supplier offer</dt>
          <dd className="mt-1 text-zinc-200">{candidate.supplierOffer ?? "unavailable from current endpoints"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Confidence</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.confidence !== null ? `${(candidate.confidence * 100).toFixed(0)}%` : "—"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Promotion state</dt>
          <dd className="mt-1 text-zinc-200">{candidate.promotionState.replace(/_/g, " ")}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Commercial decision</dt>
          <dd className="mt-1 text-zinc-200">{candidate.commercialDecision?.replace(/_/g, " ") ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Next best action</dt>
          <dd className="mt-1 text-zinc-200">{candidate.nextBestAction?.replace(/_/g, " ") ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Evidence mode</dt>
          <dd className="mt-1 text-zinc-200">{candidate.evidenceMode.replace(/_/g, " ")}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Evidence class</dt>
          <dd className="mt-1 text-zinc-200">{candidate.evidenceClass.replace(/_/g, " ")}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Source family</dt>
          <dd className="mt-1 text-zinc-200">{candidate.sourceFamily?.replace(/_/g, " ") ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Risk</dt>
          <dd className="mt-1 text-zinc-200">{candidate.riskLevel ?? "—"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Validation priority</dt>
          <dd className="mt-1 text-zinc-200">
            {(candidate.validationPriority ?? "—").replace(/_/g, " ")}
            {candidate.validationTarget ? ` → ${candidate.validationTarget}` : ""}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Assumption ratio</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.assumptionRatio !== null
              ? `${(candidate.assumptionRatio * 100).toFixed(0)}%`
              : "—"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Evidence completeness</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.evidenceCompleteness !== null
              ? `${(candidate.evidenceCompleteness * 100).toFixed(0)}%`
              : "unavailable"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Supplier evidence class</dt>
          <dd className="mt-1 text-zinc-200">{candidate.supplierEvidenceClass.replace(/_/g, " ")}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Consumer evidence class</dt>
          <dd className="mt-1 text-zinc-200">{candidate.consumerEvidenceClass.replace(/_/g, " ")}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Consumer attention</dt>
          <dd className="mt-1 text-zinc-200">{candidate.consumerAttentionSummary?.replace(/_/g, " ") ?? "unavailable"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Competition</dt>
          <dd className="mt-1 text-zinc-200">{candidate.competitionSummary?.replace(/_/g, " ") ?? "unavailable"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Economics</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.economicsUnavailable
              ? "unavailable"
              : (candidate.economicsLabel?.replace(/_/g, " ") ?? "unavailable")}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Replay identity</dt>
          <dd className="mt-1 font-mono text-[11px] text-zinc-200">{candidate.replayIdentity ?? "unavailable"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Hard gates</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.hardGates.length ? candidate.hardGates.join(" · ") : "none listed"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Evidence references</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.evidenceReferences.length ? candidate.evidenceReferences.join(" · ") : "unavailable"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Freshness expiry</dt>
          <dd className="mt-1 text-zinc-200">{candidate.freshnessExpiry ?? "unavailable"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Supplier confidence</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.confidenceSupplier !== null ? `${(candidate.confidenceSupplier * 100).toFixed(0)}%` : "unavailable"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Marketplace confidence</dt>
          <dd className="mt-1 text-zinc-200">
            {candidate.confidenceMarketplace !== null ? `${(candidate.confidenceMarketplace * 100).toFixed(0)}%` : "unavailable"}
          </dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Launch authorized</dt>
          <dd className="mt-1 text-zinc-200">{candidate.launchAuthorizedFalse ? "false" : "unavailable"}</dd>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <dt className="text-zinc-400">Offer disposition</dt>
          <dd className="mt-1 text-zinc-200">{candidate.offerDisposition}</dd>
        </div>
      </dl>

      <CommercialReviewTags candidate={candidate} />
      <NextActionWorkflowPanel candidate={candidate} />
      <DecisionTimelinePanel candidate={candidate} />

      <div className="mt-4 grid gap-3 text-xs sm:grid-cols-3">
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <h4 className="text-zinc-400">Assumptions</h4>
          <p className="mt-1 text-zinc-300">
            {candidate.assumptions.length ? candidate.assumptions.join(" · ") : "none listed"}
          </p>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <h4 className="text-zinc-400">Missing evidence</h4>
          <p className="mt-1 text-zinc-300">
            {candidate.missingEvidence.length ? candidate.missingEvidence.join(" · ") : "none listed"}
          </p>
        </div>
        <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <h4 className="text-zinc-400">Conflicts</h4>
          <p className="mt-1 text-zinc-300">
            {candidate.conflicts.length ? candidate.conflicts.join(" · ") : "none listed"}
          </p>
        </div>
      </div>

      <h4 className="mt-4 text-xs font-medium text-zinc-300">Pillar-level evidence</h4>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {candidate.pillarCells.map((cell) => (
          <li key={cell.pillarId} className="rounded border border-zinc-800 bg-zinc-950/40 p-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="text-zinc-200">{cell.label}</span>
              <span className="text-[10px] text-zinc-400">{cell.status} · {cell.evidenceClass.replace(/_/g, " ")}</span>
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
