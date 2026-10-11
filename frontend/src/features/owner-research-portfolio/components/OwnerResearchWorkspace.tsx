import { useMemo, useState } from "react";
import type {
  DraftResearchRequest,
  OpportunityReviewModel,
  PortfolioReviewModel,
} from "../contracts/ownerResearch";
import { markPortfolioMembership } from "../lib/adaptRankingReadModel";
import { evaluateDraftResearchGate } from "../lib/adaptPortfolioReadModel";
import { announceSurface } from "../lib/announce";
import { MAX_COMPARISON_CANDIDATES, toggleComparisonCandidate } from "../lib/comparisonSelection";
import { humanize, NOT_REPORTED, uniqueStrings } from "../lib/format";
import { MODE_COPY, SAFETY_NOTE } from "../lib/stateCopy";
import { OpportunityComparison } from "./OpportunityComparison";
import { OpportunityDetail } from "./OpportunityDetail";
import { PortfolioProgressPanel } from "./PortfolioProgressPanel";
import { OPPORTUNITY_DETAIL_ID, RankedOpportunityList } from "./RankedOpportunityList";
import { QualifierBanners, SurfaceStateBanner } from "./SurfaceStateBanner";

export interface OwnerResearchWorkspaceProps {
  ranking: OpportunityReviewModel;
  portfolio: PortfolioReviewModel;
  /**
   * Integration seam. When absent, draft-research actions stay disabled even if
   * the backend reports eligibility, because nothing is connected to receive them.
   */
  onDraftResearch?: (request: DraftResearchRequest) => void;
  initialSelectedId?: string | null;
}

const WRAP = "[overflow-wrap:anywhere]";

function RunSummary({ ranking }: { ranking: OpportunityReviewModel }) {
  const { run, evidenceMode } = ranking;
  if (!run || !evidenceMode) return null;
  const mode = MODE_COPY[evidenceMode];
  return (
    <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-300" aria-label="Ranking run provenance">
      <div className="min-w-0">
        <dt className="inline text-zinc-400">Evidence mode: </dt>
        <dd className={`inline ${WRAP}`} data-run-mode={evidenceMode}>
          {mode.label}. {mode.body}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="inline text-zinc-400">Backend status: </dt>
        <dd className={`inline ${WRAP}`}>{humanize(run.overallStatus)}</dd>
      </div>
      <div className="min-w-0">
        <dt className="inline text-zinc-400">Sources: </dt>
        <dd className={`inline ${WRAP}`}>{run.sourceLabels.length > 0 ? run.sourceLabels.join(", ") : NOT_REPORTED}</dd>
      </div>
      <div className="min-w-0">
        <dt className="inline text-zinc-400">Ranking freshness: </dt>
        <dd className={`inline ${WRAP}`} data-run-freshness={run.freshness.status}>{run.freshness.label}</dd>
      </div>
      <div className="min-w-0">
        <dt className="inline text-zinc-400">Network calls: </dt>
        <dd className="inline" data-run-network={run.networkCalls ? "reported" : "none_reported"}>
          {run.networkCalls ? "reported by the backend" : "none reported"}
        </dd>
      </div>
    </dl>
  );
}

/**
 * Presentational owner-research surface: ranked candidates, evidence detail and
 * curated-portfolio progress. Pure over its props (no fetching), so every state
 * can be rendered and tested deterministically.
 */
export function OwnerResearchWorkspace({
  ranking,
  portfolio,
  onDraftResearch,
  initialSelectedId = null,
}: OwnerResearchWorkspaceProps) {
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);

  const portfolioKnown = portfolio.phase === "ready" || portfolio.phase === "empty";
  const rows = useMemo(
    () => markPortfolioMembership(ranking.rows, portfolioKnown ? portfolio.activeCandidateIds : null),
    [ranking.rows, portfolio.activeCandidateIds, portfolioKnown],
  );
  const selectedRow = rows.find((row) => row.candidateId === selectedId) ?? rows[0] ?? null;
  const comparisonSet = new Set(comparisonIds);
  const comparisonRows = rows.filter((row) => comparisonSet.has(row.candidateId));
  const rankingResolved = ranking.phase === "ready" || ranking.phase === "empty";
  const missingComparisonIds = rankingResolved
    ? comparisonIds.filter((candidateId) => !rows.some((row) => row.candidateId === candidateId))
    : [];
  const selectedForComparison = selectedRow ? comparisonSet.has(selectedRow.candidateId) : false;
  const comparisonActionDisabled = !selectedRow || (!selectedForComparison && comparisonIds.length >= MAX_COMPARISON_CANDIDATES);
  const comparisonStatus = rankingResolved
    ? comparisonRows.length === 0
      ? `No candidates selected for comparison (maximum ${MAX_COMPARISON_CANDIDATES}).`
      : `${comparisonRows.length} candidate${comparisonRows.length === 1 ? "" : "s"} selected for comparison (maximum ${MAX_COMPARISON_CANDIDATES}).`
    : "Comparison is unavailable until the ranking is ready.";
  const rankedIds = useMemo(() => (rows.length > 0 ? new Set(rows.map((row) => row.candidateId)) : null), [rows]);
  const gate = useMemo(
    () => evaluateDraftResearchGate(portfolio, { handlerConnected: typeof onDraftResearch === "function" }),
    [portfolio, onDraftResearch],
  );
  // Adapter warnings (dropped duplicate/malformed rows, rank problems) must be visible, not just counted.
  const rankingDetails = useMemo(
    () => uniqueStrings([...ranking.reasons, ...ranking.warnings]),
    [ranking.reasons, ranking.warnings],
  );
  const announcement = announceSurface(ranking, portfolio);

  function toggleSelectedComparison() {
    if (!selectedRow) return;
    const candidateId = selectedRow.candidateId;
    setComparisonIds((current) => toggleComparisonCandidate(current, candidateId));
  }

  function removeComparisonCandidate(candidateId: string) {
    setComparisonIds((current) => current.filter((id) => id !== candidateId));
  }

  function removeUnavailableComparisonCandidates() {
    const visibleIds = new Set(rows.map((row) => row.candidateId));
    setComparisonIds((current) => current.filter((id) => visibleIds.has(id)));
  }

  function focusDetail() {
    document.getElementById(OPPORTUNITY_DETAIL_ID)?.focus();
  }

  return (
    <section aria-labelledby="owner-research-heading" data-owner-research-workspace className="min-w-0 space-y-4 text-zinc-100">
      <p role="status" aria-live="polite" aria-atomic="true" className="sr-only" data-live-summary>
        {announcement}
      </p>

      <header>
        <h1 id="owner-research-heading" className="text-lg font-semibold">Owner research: opportunity review</h1>
        <p className="mt-1 text-sm text-zinc-300">{SAFETY_NOTE}</p>
        <RunSummary ranking={ranking} />
      </header>

      <QualifierBanners
        scopes={[
          { scope: "ranking", qualifiers: ranking.qualifiers },
          { scope: "portfolio", qualifiers: portfolio.qualifiers },
        ]}
      />
      <SurfaceStateBanner
        scope="ranking"
        phase={ranking.phase}
        reasons={rankingDetails}
        openReasons={ranking.qualifiers.includes("blocked")}
      />
      <SurfaceStateBanner scope="portfolio" phase={portfolio.phase} reasons={portfolio.reasons} />

      <PortfolioProgressPanel
        portfolio={portfolio}
        gate={gate}
        rankedCandidateIds={rankedIds}
        onDraftResearch={onDraftResearch}
      />

      {rows.length > 0 ? (
        <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-2">
          <RankedOpportunityList
            rows={rows}
            selectedId={selectedRow?.candidateId ?? null}
            hiddenRows={ranking.dropped}
            onSelect={setSelectedId}
            onActivate={(candidateId) => {
              setSelectedId(candidateId);
              focusDetail();
            }}
          />
          <OpportunityDetail row={selectedRow} run={ranking.run} />
        </div>
      ) : (
        <section
          aria-labelledby="owner-ranked-heading"
          data-ranked-empty
          className="min-w-0 rounded-lg border border-dashed border-zinc-700 bg-zinc-900/30 p-3 sm:p-4"
        >
          <h2 id="owner-ranked-heading" className="text-base font-semibold text-zinc-100">Ranked opportunities</h2>
          <p className="mt-1 text-sm text-zinc-400">
            No ranked candidates are shown. The ranking state above explains why.
          </p>
        </section>
      )}

      <section
        aria-labelledby="owner-comparison-heading"
        data-owner-comparison
        className="min-w-0 space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 sm:p-4"
      >
        <header>
          <h2 id="owner-comparison-heading" className="text-base font-semibold text-zinc-100">Compare opportunities</h2>
          <p className="mt-1 text-sm text-zinc-300">
            Compare up to {MAX_COMPARISON_CANDIDATES} candidates using reported evidence and the next action from Product Opportunity Synthesis.
          </p>
          <p className="mt-1 text-xs text-zinc-400">
            Supplier evidence classes are not confirmation of inventory or availability. Public-market and consumer-attention signals are context, not supplier proof. Fixture, manual and simulated modes remain labelled; planning assumptions stay separate.
          </p>
          <p className="mt-1 text-xs text-zinc-400">
            Backend rank and pillar values are displayed as reported. This comparison preserves backend order and does not calculate a winner or a new score.
          </p>
        </header>

        <div className="flex flex-wrap items-center gap-3">
          <p
            role="status"
            aria-live="polite"
            aria-atomic="true"
            data-comparison-count={comparisonRows.length}
            className="text-sm text-zinc-200"
          >
            {comparisonStatus}
          </p>
          <button
            type="button"
            data-comparison-toggle
            aria-pressed={selectedForComparison}
            aria-label={selectedRow
              ? `${selectedForComparison ? "Remove" : "Add"} ${selectedRow.title ?? "selected candidate"} (${selectedRow.candidateId}) ${selectedForComparison ? "from" : "to"} comparison`
              : "Select a ranked candidate before comparing"}
            aria-describedby="owner-comparison-action-hint"
            disabled={comparisonActionDisabled}
            onClick={toggleSelectedComparison}
            className="min-h-[44px] rounded-lg border border-sky-400/70 bg-sky-500/10 px-3 py-2 text-sm text-sky-100 hover:bg-sky-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:cursor-not-allowed disabled:border-zinc-700 disabled:bg-zinc-900 disabled:text-zinc-400"
          >
            {selectedForComparison ? "Remove from comparison" : "Add to comparison"}
          </button>
        </div>
        <p id="owner-comparison-action-hint" className="text-xs text-zinc-400">
          {selectedRow
            ? comparisonActionDisabled && !selectedForComparison
              ? "The comparison is full. Remove a candidate before adding another."
              : `Current candidate: ${selectedRow.title ?? "Untitled candidate"} (${selectedRow.candidateId}).`
            : "Select a ranked opportunity to add it to the comparison."}
        </p>

        {comparisonRows.length === 0 && comparisonIds.length === 0 ? (
          <p className="text-sm text-zinc-400">No candidates selected yet. Choose a ranked candidate and add it here.</p>
        ) : null}
        {comparisonRows.length === 0 && comparisonIds.length > 0 && !rankingResolved ? (
          <p className="text-sm text-zinc-400">Selected candidates are hidden until the current ranking is available.</p>
        ) : null}
        {comparisonRows.length === 1 ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-zinc-800 bg-zinc-950/40 p-3">
            <p className="min-w-0 text-sm text-zinc-200 [overflow-wrap:anywhere]">
              One candidate selected: {comparisonRows[0].title ?? "Untitled candidate"} ({comparisonRows[0].candidateId}). Add one more for a side-by-side comparison.
            </p>
            <button
              type="button"
              onClick={() => removeComparisonCandidate(comparisonRows[0].candidateId)}
              aria-label={`Remove ${comparisonRows[0].title ?? "candidate"} (${comparisonRows[0].candidateId}) from comparison`}
              className="min-h-[44px] rounded border border-zinc-600 px-3 py-2 text-xs text-zinc-100 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
            >
              Remove
            </button>
          </div>
        ) : null}
        {comparisonRows.length >= 2 ? (
          <OpportunityComparison rows={comparisonRows} onRemove={removeComparisonCandidate} />
        ) : null}
        {missingComparisonIds.length > 0 ? (
          <div role="status" aria-live="polite" className="rounded border border-amber-700/70 bg-amber-950/20 p-3 text-sm text-amber-100">
            <p>{missingComparisonIds.length} selected candidate{missingComparisonIds.length === 1 ? " no longer appears" : "s no longer appear"} in the current ranking and {missingComparisonIds.length === 1 ? "is" : "are"} omitted from the comparison.</p>
            <button
              type="button"
              onClick={removeUnavailableComparisonCandidates}
              className="mt-2 min-h-[44px] rounded border border-amber-500/70 px-3 py-2 text-xs hover:bg-amber-900/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-300"
            >
              Remove unavailable candidates
            </button>
          </div>
        ) : null}
      </section>
    </section>
  );
}
