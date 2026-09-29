import { useMemo } from "react";
import { useFirstPhaseEvidenceCockpit } from "../first-phase-cockpit/hooks/useFirstPhaseEvidenceCockpit";
import { OwnerResearchWorkspace } from "./components/OwnerResearchWorkspace";
import type { DraftResearchRequest } from "./contracts/ownerResearch";
import {
  FIXTURE_PORTFOLIO_PAYLOAD,
  FIXTURE_RANKING_PACKET,
  FIXTURE_WORKSPACE_ID,
} from "./fixtures/ownerResearchFixtures";
import { useNow } from "./hooks/useNow";
import { useOwnerPortfolio } from "./hooks/useOwnerPortfolio";
import { adaptPortfolioPayload } from "./lib/adaptPortfolioReadModel";
import { adaptRankingPacket } from "./lib/adaptRankingReadModel";

export interface OwnerResearchPortfolioPageProps {
  /** Tenant to read. There is no default workspace: without one the portfolio is `unavailable`. */
  workspaceId?: string | null;
  /** `live` (default) reads canonical endpoints; `fixture` is explicit, labelled and never live. */
  source?: "live" | "fixture";
  /** Integration seam for draft research. Absent => actions stay disabled. */
  onDraftResearch?: (request: DraftResearchRequest) => void;
}

function readSearchParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(name);
}

function LiveOwnerResearch({
  workspaceId,
  onDraftResearch,
}: {
  workspaceId: string | null;
  onDraftResearch?: (request: DraftResearchRequest) => void;
}) {
  // Canonical ranking read model: composed from the existing read-only endpoints.
  const { packet, isLoading, hasErrors } = useFirstPhaseEvidenceCockpit();
  const nowMs = useNow();
  const { portfolio, refresh } = useOwnerPortfolio(workspaceId, { nowMs });
  const ranking = useMemo(
    () =>
      adaptRankingPacket({
        packet,
        loading: isLoading,
        loadError: hasErrors ? "canonical_read_failed" : null,
        nowMs,
      }),
    [packet, isLoading, hasErrors, nowMs],
  );

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={refresh}
          className="min-h-[44px] rounded-lg border border-zinc-600 px-3 py-2 text-sm text-zinc-100 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
        >
          Refresh portfolio (read-only)
        </button>
      </div>
      <OwnerResearchWorkspace ranking={ranking} portfolio={portfolio} onDraftResearch={onDraftResearch} />
    </div>
  );
}

function FixtureOwnerResearch({ onDraftResearch }: { onDraftResearch?: (request: DraftResearchRequest) => void }) {
  const nowMs = useNow();
  const ranking = useMemo(
    () => adaptRankingPacket({ packet: FIXTURE_RANKING_PACKET, loading: false, loadError: null, nowMs }),
    [nowMs],
  );
  const portfolio = useMemo(
    () => adaptPortfolioPayload(FIXTURE_PORTFOLIO_PAYLOAD, { expectedWorkspaceId: FIXTURE_WORKSPACE_ID, nowMs }),
    [nowMs],
  );
  return <OwnerResearchWorkspace ranking={ranking} portfolio={portfolio} onDraftResearch={onDraftResearch} />;
}

/**
 * Owner research page container. NOT mounted anywhere yet: routing, Sidebar and
 * Shell are intentionally untouched. To mount it, add a route element for this
 * default export (see docs/FRONTEND_OWNER_RESEARCH_PORTFOLIO.md).
 */
export default function OwnerResearchPortfolioPage({
  workspaceId,
  source,
  onDraftResearch,
}: OwnerResearchPortfolioPageProps) {
  const resolvedSource = source ?? (readSearchParam("source") === "fixture" ? "fixture" : "live");
  const resolvedWorkspace = (workspaceId ?? readSearchParam("workspace_id"))?.trim() || null;

  return (
    <div className="mx-auto w-full max-w-6xl p-3 sm:p-6">
      {resolvedSource === "fixture" ? (
        <FixtureOwnerResearch onDraftResearch={onDraftResearch} />
      ) : (
        <LiveOwnerResearch workspaceId={resolvedWorkspace} onDraftResearch={onDraftResearch} />
      )}
    </div>
  );
}
