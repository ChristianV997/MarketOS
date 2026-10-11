import type { ReactNode } from "react";
import type { OpportunityRow, PillarReview } from "../contracts/ownerResearch";
import { formatReportedScore, humanize, NOT_REPORTED } from "../lib/format";
import { MODE_COPY } from "../lib/stateCopy";

const WRAP = "[overflow-wrap:anywhere]";

type ComparisonMetric = {
  id: string;
  label: string;
  render: (row: OpportunityRow) => ReactNode;
};

function ReportedList({
  items,
  empty,
}: {
  items: readonly string[];
  empty: string;
}) {
  if (items.length === 0) return <p className="text-zinc-400">{empty}</p>;
  return (
    <ul className="list-disc space-y-1 pl-5">
      {items.map((item, index) => (
        <li key={`${index}:${item}`} className={WRAP}>{item}</li>
      ))}
    </ul>
  );
}

function PillarEvidence({
  row,
  pillarId,
}: {
  row: OpportunityRow;
  pillarId: PillarReview["id"];
}) {
  const pillars = row.pillars.filter((pillar) => pillar.id === pillarId);
  if (pillars.length === 0) return <p>{NOT_REPORTED}</p>;

  return (
    <ul className="space-y-2">
      {pillars.map((pillar, index) => (
        <li key={`${pillar.id}:${index}`} className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
          <p className="font-medium">{pillar.label}</p>
          <p>Status: {humanize(pillar.status)}</p>
          <p>Reported score: {formatReportedScore(pillar.score)}</p>
          <p>Evidence class: {humanize(pillar.evidenceClass)}</p>
          <p className={WRAP}>Detail: {pillar.detail ?? NOT_REPORTED}</p>
        </li>
      ))}
    </ul>
  );
}

function evidenceMode(row: OpportunityRow): ReactNode {
  const mode = MODE_COPY[row.provenance.evidenceMode];
  return (
    <dl className="space-y-1">
      <div>
        <dt className="font-medium text-zinc-300">Evidence mode</dt>
        <dd>{mode.label}. {mode.body}</dd>
      </div>
      <div>
        <dt className="font-medium text-zinc-300">Candidate evidence class</dt>
        <dd>{humanize(row.provenance.evidenceClass)}</dd>
      </div>
      <div>
        <dt className="font-medium text-zinc-300">Source family</dt>
        <dd className={WRAP}>{humanize(row.provenance.sourceFamily)}</dd>
      </div>
    </dl>
  );
}

const METRICS: readonly ComparisonMetric[] = [
  {
    id: "rank",
    label: "Backend rank",
    render: (row) => row.rankNumber !== null
      ? `#${row.rankNumber}`
      : `Position ${row.position}; rank ${NOT_REPORTED.toLowerCase()}`,
  },
  {
    id: "decision",
    label: "Commercial decision reported by synthesis",
    render: (row) => humanize(row.commercialDecision),
  },
  {
    id: "next-action",
    label: "Next action from synthesis",
    render: (row) => humanize(row.nextBestAction),
  },
  {
    id: "supplier",
    label: "Supplier evidence class",
    render: (row) => <p>{humanize(row.provenance.supplierEvidenceClass)}</p>,
  },
  {
    id: "market",
    label: "Public-market context",
    render: (row) => <PillarEvidence row={row} pillarId="market_evidence" />,
  },
  {
    id: "consumer-attention",
    label: "Consumer-attention evidence",
    render: (row) => (
      <div className="space-y-2">
        <p>Evidence class: {humanize(row.provenance.consumerEvidenceClass)}</p>
        <PillarEvidence row={row} pillarId="consumer_attention" />
      </div>
    ),
  },
  {
    id: "provenance",
    label: "Input mode and provenance",
    render: evidenceMode,
  },
  {
    id: "freshness",
    label: "Freshness",
    render: (row) => <p data-freshness-status={row.freshness.status}>{row.freshness.label}</p>,
  },
  {
    id: "gaps",
    label: "Evidence gaps",
    render: (row) => <ReportedList items={row.gaps} empty="No evidence gaps were reported." />,
  },
  {
    id: "gates",
    label: "Blocking gates",
    render: (row) => <ReportedList items={row.hardGates} empty="No blocking gates were reported." />,
  },
  {
    id: "conflicts",
    label: "Conflicts",
    render: (row) => <ReportedList items={row.conflicts} empty="No conflicts were reported." />,
  },
  {
    id: "assumptions",
    label: "Planning assumptions",
    render: (row) => <ReportedList items={row.assumptions} empty="No planning assumptions were reported." />,
  },
];

function rankLabel(row: OpportunityRow): string {
  return row.rankNumber !== null ? `Backend rank #${row.rankNumber}` : `Backend rank not reported; position ${row.position}`;
}

/**
 * Side-by-side view of the canonical synthesis fields. The input array is
 * rendered as supplied: this component never sorts, scores, blends or selects a
 * winning candidate.
 */
export function OpportunityComparison({
  rows,
  onRemove,
}: {
  rows: readonly OpportunityRow[];
  onRemove: (candidateId: string) => void;
}) {
  if (rows.length < 2) return null;

  return (
    <div className="mt-4 min-w-0">
      <div
        role="region"
        aria-labelledby="owner-comparison-table-caption"
        aria-describedby="owner-comparison-table-hint"
        tabIndex={0}
        className="max-w-full overflow-x-auto rounded-lg border border-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
      >
        <table data-comparison-table className="w-full min-w-[60rem] border-collapse text-left text-sm">
          <caption id="owner-comparison-table-caption" className="sr-only">
            Opportunity evidence comparison, preserving backend order
          </caption>
          <thead>
            <tr className="border-b border-zinc-700 bg-zinc-950/70">
              <th scope="col" className="sticky left-0 z-10 min-w-48 bg-zinc-950 p-3 align-top text-xs font-semibold text-zinc-300">
                Evidence dimension
              </th>
              {rows.map((row) => (
                <th key={row.candidateId} scope="col" className="min-w-64 border-l border-zinc-800 p-3 align-top">
                  <p className={`font-semibold text-zinc-100 ${WRAP}`}>{row.title ?? "Untitled candidate"}</p>
                  <p className={`mt-1 font-mono text-xs text-zinc-400 ${WRAP}`}>Candidate ID: {row.candidateId}</p>
                  <p className="mt-1 text-xs text-zinc-300">{rankLabel(row)}</p>
                  <button
                    type="button"
                    onClick={() => onRemove(row.candidateId)}
                    aria-label={`Remove ${row.title ?? "candidate"} (${row.candidateId}) from comparison`}
                    className="mt-2 inline-flex min-h-[44px] items-center rounded border border-zinc-600 px-3 py-2 text-xs text-zinc-100 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
                  >
                    Remove
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {METRICS.map((metric) => (
              <tr key={metric.id} className="border-b border-zinc-800 last:border-b-0">
                <th scope="row" className="sticky left-0 z-10 min-w-48 bg-zinc-900 p-3 align-top text-xs font-semibold text-zinc-200">
                  {metric.label}
                </th>
                {rows.map((row) => (
                  <td key={row.candidateId} className={`min-w-64 border-l border-zinc-800 p-3 align-top text-xs text-zinc-100 ${WRAP}`}>
                    {metric.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p id="owner-comparison-table-hint" className="mt-2 text-xs text-zinc-400">
        Use the scroll region to compare all candidate columns. Reported pillar scores are not combined into another score.
      </p>
    </div>
  );
}
