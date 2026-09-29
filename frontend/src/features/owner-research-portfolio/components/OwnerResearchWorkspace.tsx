import { useMemo, useState } from "react";
import type {
  DraftResearchRequest,
  OpportunityReviewModel,
  PortfolioReviewModel,
} from "../contracts/ownerResearch";
import { markPortfolioMembership } from "../lib/adaptRankingReadModel";
import { evaluateDraftResearchGate } from "../lib/adaptPortfolioReadModel";
import { humanize, NOT_REPORTED } from "../lib/format";
import { MODE_COPY, SAFETY_NOTE } from "../lib/stateCopy";
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

const CHIP = "inline-flex items-center rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[11px] text-zinc-200";

function RunSummary({ ranking }: { ranking: OpportunityReviewModel }) {
  const { run, evidenceMode } = ranking;
  if (!run || !evidenceMode) return null;
  const mode = MODE_COPY[evidenceMode];
  return (
    <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-300" aria-label="Ranking run provenance">
      <div>
        <dt className="inline text-zinc-400">Evidence mode: </dt>
        <dd className="inline" data-run-mode={evidenceMode}>{mode.label}</dd>
      </div>
      <div>
        <dt className="inline text-zinc-400">Backend status: </dt>
        <dd className="inline">{humanize(run.overallStatus)}</dd>
      </div>
      <div>
        <dt className="inline text-zinc-400">Sources: </dt>
        <dd className="inline break-words">{run.sourceLabels.length > 0 ? run.sourceLabels.join(", ") : NOT_REPORTED}</dd>
      </div>
      <div>
        <dt className="inline text-zinc-400">Ranking freshness: </dt>
        <dd className="inline" data-run-freshness={run.freshness.status}>{run.freshness.label}</dd>
      </div>
      <div>
        <dt className="inline text-zinc-400">Network calls reported: </dt>
        <dd className="inline">{run.networkCalls ? "yes" : "no"}</dd>
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

  const portfolioKnown = portfolio.phase === "ready" || portfolio.phase === "empty";
  const rows = useMemo(
    () => markPortfolioMembership(ranking.rows, portfolioKnown ? portfolio.activeCandidateIds : null),
    [ranking.rows, portfolio.activeCandidateIds, portfolioKnown],
  );
  const selectedRow = rows.find((row) => row.candidateId === selectedId) ?? rows[0] ?? null;
  const rankedIds = useMemo(() => (rows.length > 0 ? new Set(rows.map((row) => row.candidateId)) : null), [rows]);
  const gate = useMemo(
    () => evaluateDraftResearchGate(portfolio, { handlerConnected: typeof onDraftResearch === "function" }),
    [portfolio, onDraftResearch],
  );

  function focusDetail() {
    document.getElementById(OPPORTUNITY_DETAIL_ID)?.focus();
  }

  return (
    <section aria-labelledby="owner-research-heading" data-owner-research-workspace className="min-w-0 space-y-4 text-zinc-100">
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
        reasons={ranking.reasons}
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
            onSelect={setSelectedId}
            onActivate={(candidateId) => {
              setSelectedId(candidateId);
              focusDetail();
            }}
          />
          <OpportunityDetail row={selectedRow} run={ranking.run} />
        </div>
      ) : null}
    </section>
  );
}
