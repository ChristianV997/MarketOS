import type { OwnerDashboardViewModel } from "../contracts/ownerDashboard";
import { CandidateDetail } from "./CandidateDetail";
import { NoticeList } from "./NoticeList";
import { OpportunityLists } from "./OpportunityLists";
import { PerformancePanel } from "./PerformancePanel";
import { ReadinessSummaryPanel } from "./ReadinessSummaryPanel";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

export interface OwnerDashboardViewProps {
  viewModel: OwnerDashboardViewModel;
  selectedId: string | null;
  onSelect: (candidateId: string) => void;
  onRetry: () => void;
  isRetrying?: boolean;
  /** Incremented on a user selection so focus moves to the detail heading. */
  focusToken?: number;
}

export function OwnerDashboardView({
  viewModel,
  selectedId,
  onSelect,
  onRetry,
  isRetrying = false,
  focusToken = 0,
}: OwnerDashboardViewProps) {
  const all = [...viewModel.ranked, ...viewModel.unranked];
  const selected = all.find((candidate) => candidate.candidateId === selectedId) ?? all[0] ?? null;

  return (
    <section aria-labelledby="owner-heading" className="mx-auto w-full max-w-7xl space-y-5 p-4 sm:p-6">
      <header className="space-y-1">
        <h1 id="owner-heading" className="text-lg font-semibold text-zinc-100">
          Owner cockpit
        </h1>
        <p className="max-w-3xl text-sm text-zinc-400">
          Your own product discovery and portfolio. MarketOS recommends and explains; Shopify remains the commerce
          execution authority, and everything here is advisory.
        </p>
      </header>

      <NoticeList notices={viewModel.notices} />

      {viewModel.status === "loading" ? <LoadingState /> : null}
      {viewModel.status === "unavailable" && viewModel.error ? (
        <ErrorState error={viewModel.error} heading="Owner dashboard unavailable" onRetry={onRetry} isRetrying={isRetrying} />
      ) : null}
      {viewModel.status === "malformed" && viewModel.error ? (
        <ErrorState error={viewModel.error} heading="The discovery response could not be read" onRetry={onRetry} isRetrying={isRetrying} />
      ) : null}
      {viewModel.status === "empty" ? <EmptyState run={viewModel.run} /> : null}

      {viewModel.status === "ready" && viewModel.summary && viewModel.run ? (
        <>
          <a
            href="#owner-candidate-detail"
            className="sr-only focus:not-sr-only focus:inline-block focus:rounded focus:bg-indigo-500 focus:px-3 focus:py-1.5 focus:text-sm focus:text-white"
          >
            Skip to selected opportunity details
          </a>
          <ReadinessSummaryPanel summary={viewModel.summary} run={viewModel.run} />
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <OpportunityLists
              ranked={viewModel.ranked}
              unranked={viewModel.unranked}
              selectedId={selected?.candidateId ?? null}
              onSelect={onSelect}
            />
            {selected ? (
              <div className="min-w-0 lg:self-start">
                <CandidateDetail candidate={selected} saveToPortfolio={viewModel.saveToPortfolio} focusToken={focusToken} />
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      {viewModel.status === "ready" || viewModel.status === "empty" ? (
        <PerformancePanel performance={viewModel.performance} />
      ) : null}
    </section>
  );
}
