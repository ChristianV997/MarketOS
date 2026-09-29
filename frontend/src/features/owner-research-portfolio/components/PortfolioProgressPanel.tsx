import {
  DRAFT_RESEARCH_ACTIONS,
  type DraftResearchGate,
  type DraftResearchRequest,
  type PortfolioReviewModel,
} from "../contracts/ownerResearch";
import { MODE_COPY } from "../lib/stateCopy";

const CHIP = "inline-flex items-center rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[11px] text-zinc-200";

function eligibilityLabel(portfolio: PortfolioReviewModel): { key: string; text: string } {
  if (portfolio.phase === "loading" || portfolio.phase === "error" || portfolio.phase === "unavailable") {
    return { key: "unknown", text: "Eligibility unknown: the portfolio is not available." };
  }
  if (!portfolio.eligibility.reported) return { key: "not_reported", text: "Eligibility not reported by the backend." };
  return portfolio.eligibility.eligible
    ? { key: "eligible", text: "Backend reports eligible for draft research." }
    : { key: "not_eligible", text: "Backend reports not eligible for draft research." };
}

/**
 * Curated portfolio progress. X/3 counts DISTINCT ACTIVE candidate ids only.
 * An unknown portfolio shows "—/3" (never 0/3). Draft-research actions are
 * native-disabled unless the backend has explicitly reported eligibility.
 */
export function PortfolioProgressPanel({
  portfolio,
  gate,
  rankedCandidateIds,
  onDraftResearch,
}: {
  portfolio: PortfolioReviewModel;
  gate: DraftResearchGate;
  /** Ids in the current ranking, when known; used only to flag portfolio ids outside it. */
  rankedCandidateIds: ReadonlySet<string> | null;
  onDraftResearch?: (request: DraftResearchRequest) => void;
}) {
  const count = portfolio.activeCount;
  const eligibility = eligibilityLabel(portfolio);
  const mode = portfolio.evidenceMode ? MODE_COPY[portfolio.evidenceMode] : null;
  const { ignored } = portfolio;

  return (
    <section
      aria-labelledby="owner-portfolio-heading"
      data-portfolio-phase={portfolio.phase}
      className="min-w-0 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 sm:p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="owner-portfolio-heading" className="text-base font-semibold text-zinc-100">Curated portfolio</h2>
        <p className="text-xs text-zinc-400">
          {portfolio.workspaceId ? <>Workspace <span className="break-all font-mono">{portfolio.workspaceId}</span></> : "No workspace selected"}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <p className="text-2xl font-semibold text-zinc-100" data-portfolio-count={count === null ? "unknown" : String(count)}>
          <span aria-hidden="true">{count === null ? "—" : count}/{portfolio.required}</span>
          <span className="sr-only">
            {count === null
              ? `Progress unknown: portfolio not available, ${portfolio.required} distinct active candidates required`
              : `${count} of ${portfolio.required} distinct active candidates`}
          </span>
        </p>
        {count !== null ? (
          <progress
            value={Math.min(count, portfolio.required)}
            max={portfolio.required}
            aria-label={`Distinct active candidates toward ${portfolio.required}`}
            className="h-2 w-40 max-w-full accent-sky-400"
          />
        ) : null}
        <p className="text-sm text-zinc-300">distinct active candidate IDs</p>
      </div>
      <p className="mt-1 text-xs text-zinc-400">
        SKUs, supplier offers, quantities and repeated rows are never counted.
      </p>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {mode ? <span className={CHIP} data-portfolio-mode={portfolio.evidenceMode}>{mode.label}</span> : null}
        <span className={CHIP} data-portfolio-freshness={portfolio.freshness.status}>{portfolio.freshness.label}</span>
      </div>

      {portfolio.activeCandidateIds.length > 0 ? (
        <div className="mt-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-300">Active candidates</h3>
          <ul aria-label="Active curated candidate IDs" className="mt-1 flex flex-wrap gap-1.5">
            {portfolio.activeCandidateIds.map((id) => (
              <li key={id} className={`${CHIP} break-all font-mono`}>
                {id}
                {rankedCandidateIds && !rankedCandidateIds.has(id) ? <span className="ml-1 font-sans text-zinc-400">(not in current ranking)</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {portfolio.phase === "ready" || portfolio.phase === "empty" ? (
        <ul className="mt-3 space-y-0.5 text-xs text-zinc-400" aria-label="Entries not counted">
          {ignored.duplicateActiveRows > 0 ? <li>{ignored.duplicateActiveRows} repeated row(s) for already-counted IDs were ignored.</li> : null}
          {ignored.notActive > 0 ? <li>{ignored.notActive} inactive, removed or archived entr{ignored.notActive === 1 ? "y is" : "ies are"} not counted.</li> : null}
          {ignored.invalidId > 0 ? <li>{ignored.invalidId} entr{ignored.invalidId === 1 ? "y" : "ies"} with a missing or malformed candidate ID {ignored.invalidId === 1 ? "was" : "were"} ignored.</li> : null}
          {ignored.unknownStatus > 0 ? <li>{ignored.unknownStatus} entr{ignored.unknownStatus === 1 ? "y" : "ies"} with an unknown status {ignored.unknownStatus === 1 ? "was" : "were"} ignored.</li> : null}
          {ignored.malformedEntries > 0 ? <li>{ignored.malformedEntries} malformed entr{ignored.malformedEntries === 1 ? "y was" : "ies were"} ignored.</li> : null}
        </ul>
      ) : null}

      <div className="mt-4 border-t border-zinc-800 pt-3">
        <h3 id="owner-draft-heading" className="text-sm font-semibold text-zinc-100">Draft research (advisory)</h3>
        <p className="mt-1 text-sm text-zinc-300" data-eligibility={eligibility.key}>{eligibility.text}</p>
        <div
          role="group"
          aria-labelledby="owner-draft-heading"
          aria-describedby={gate.enabled ? undefined : "owner-draft-reasons"}
          className="mt-2 flex flex-wrap gap-2"
        >
          {DRAFT_RESEARCH_ACTIONS.map((action) => (
            <button
              key={action.id}
              type="button"
              disabled={!gate.enabled}
              data-draft-action={action.id}
              onClick={() => {
                if (gate.enabled) onDraftResearch?.({ actionId: action.id, activeCandidateIds: portfolio.activeCandidateIds });
              }}
              className="min-h-[44px] rounded-lg border border-sky-400/70 bg-sky-500/10 px-3 py-2 text-left text-sm text-sky-100 hover:bg-sky-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:cursor-not-allowed disabled:border-zinc-700 disabled:bg-zinc-900 disabled:text-zinc-400"
            >
              {action.label}
            </button>
          ))}
        </div>
        {!gate.enabled ? (
          <div id="owner-draft-reasons" className="mt-2 text-xs text-zinc-300" data-draft-gate="disabled">
            <p className="font-medium">Draft research is unavailable because:</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {gate.reasons.map((reason) => (
                <li key={reason} className="break-words">{reason}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="mt-2 text-xs text-zinc-400" data-draft-gate="enabled">
            Choosing an action sends a draft-research request to the connected service. This page changes nothing itself.
          </p>
        )}
      </div>
    </section>
  );
}
