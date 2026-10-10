import type { OpportunityRow, RankingRunMeta } from "../contracts/ownerResearch";
import { formatReportedScore, humanize, NOT_REPORTED } from "../lib/format";
import { MODE_COPY } from "../lib/stateCopy";
import { OPPORTUNITY_DETAIL_ID } from "./RankedOpportunityList";

const WRAP = "[overflow-wrap:anywhere]";

function ListOrNone({
  heading,
  items,
  none,
  className = "",
}: {
  heading: string;
  items: readonly string[];
  none: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-300">{heading}</h4>
      {items.length > 0 ? (
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-zinc-100">
          {items.map((item) => (
            <li key={item} className={WRAP}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-zinc-400">{none}</p>
      )}
    </div>
  );
}

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-zinc-400">{term}</dt>
      <dd className={`text-sm text-zinc-100 ${WRAP}`}>{children}</dd>
    </div>
  );
}

/**
 * Selected candidate: evidence pillars, gaps, provenance and freshness.
 * Everything is shown exactly as reported; nothing is scored, summed or defaulted.
 */
export function OpportunityDetail({ row, run }: { row: OpportunityRow | null; run: RankingRunMeta | null }) {
  if (!row) {
    return (
      <section
        id={OPPORTUNITY_DETAIL_ID}
        tabIndex={-1}
        aria-labelledby="owner-detail-heading"
        className="min-w-0 rounded-lg border border-dashed border-zinc-700 bg-zinc-900/30 p-4 text-sm text-zinc-300 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
      >
        <h3 id="owner-detail-heading" className="text-base font-semibold text-zinc-100">Candidate details</h3>
        <p className="mt-2">Select a ranked candidate to review its evidence pillars, gaps, provenance and freshness.</p>
      </section>
    );
  }

  const mode = MODE_COPY[row.provenance.evidenceMode];

  return (
    <section
      id={OPPORTUNITY_DETAIL_ID}
      tabIndex={-1}
      aria-labelledby="owner-detail-heading"
      data-candidate-id={row.candidateId}
      className="min-w-0 space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 sm:p-4"
    >
      <header>
        <h3 id="owner-detail-heading" className={`text-base font-semibold text-zinc-100 ${WRAP}`}>
          {row.title ?? "Untitled candidate"}
        </h3>
        <p className={`font-mono text-xs text-zinc-400 ${WRAP}`}>Candidate ID: {row.candidateId}</p>
      </header>

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Fact term="Backend rank">{row.rankNumber !== null ? `#${row.rankNumber}` : `Position ${row.position} (rank not reported)`}</Fact>
        <Fact term="Promotion state">{humanize(row.promotionState)}</Fact>
        <Fact term="Commercial decision">{humanize(row.commercialDecision)}</Fact>
        <Fact term="Risk level">{humanize(row.riskLevel)}</Fact>
        <Fact term="Evidence completeness">{formatReportedScore(row.evidenceCompleteness)}</Fact>
        <Fact term="Confidence">{formatReportedScore(row.confidence)}</Fact>
        <Fact term="Next best action">{humanize(row.nextBestAction)}</Fact>
      </dl>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-300">Evidence pillars</h4>
        {row.pillars.length > 0 ? (
          <ul aria-label={`Evidence pillars for ${row.title ?? row.candidateId}, exactly as reported`} className="mt-2 space-y-2">
            {row.pillars.map((pillar) => (
              <li key={pillar.id} data-pillar={pillar.id} className="rounded border border-zinc-800 bg-zinc-950/40 p-2 text-sm">
                <p className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                  <span className="font-medium text-zinc-100">{pillar.label}</span>
                  <span className="text-zinc-300" data-pillar-status={pillar.status}>Status: {humanize(pillar.status)}</span>
                  <span className="text-zinc-300">Reported score: {formatReportedScore(pillar.score)}</span>
                </p>
                <p className={`mt-0.5 text-xs text-zinc-400 ${WRAP}`}>
                  Evidence class: {humanize(pillar.evidenceClass)}
                  {pillar.detail ? ` · ${pillar.detail}` : ` · Detail: ${NOT_REPORTED}`}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-zinc-400">No pillar breakdown was reported for this candidate.</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ListOrNone heading="Evidence gaps" items={row.gaps} none="No evidence gaps were reported by the backend." />
        <ListOrNone heading="Blocking gates" items={row.hardGates} none="No blocking gates were reported." />
        <ListOrNone heading="Conflicts" items={row.conflicts} none="No conflicts were reported." />
        <ListOrNone heading="Assumptions" items={row.assumptions} none="No assumptions were reported." />
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-300">Provenance</h4>
        <dl className="mt-1 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Fact term="Evidence mode">
            {mode.label}. {mode.body}
          </Fact>
          <Fact term="Evidence class">{humanize(row.provenance.evidenceClass)}</Fact>
          <Fact term="Supplier evidence class">{humanize(row.provenance.supplierEvidenceClass)}</Fact>
          <Fact term="Consumer evidence class">{humanize(row.provenance.consumerEvidenceClass)}</Fact>
          <Fact term="Source family">{humanize(row.provenance.sourceFamily)}</Fact>
          <Fact term="Replay identity">{row.provenance.replayIdentity ?? NOT_REPORTED}</Fact>
          <Fact term="Read model schema">{run?.schemaVersion ?? NOT_REPORTED}</Fact>
          <Fact term="Report version">{run?.reportVersion ?? NOT_REPORTED}</Fact>
        </dl>
        <ListOrNone
          className="mt-3"
          heading="Evidence references"
          items={row.provenance.evidenceReferences}
          none="No evidence references were reported."
        />
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-300">Freshness</h4>
        <p className="mt-1 text-sm text-zinc-100" data-freshness-status={row.freshness.status}>{row.freshness.label}</p>
        {run ? (
          <p className="mt-1 text-xs text-zinc-400" data-run-freshness-status={run.freshness.status}>
            Run: {run.freshness.label}
          </p>
        ) : null}
      </div>

      <p className="text-xs text-zinc-400">
        Advisory only. This candidate carries no launch, publishing, spend, order or provider authority.
      </p>
    </section>
  );
}
