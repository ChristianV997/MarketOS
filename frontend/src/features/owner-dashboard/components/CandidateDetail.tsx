import { useEffect, useRef } from "react";
import { Lock } from "lucide-react";
import type { OwnerCandidate, OwnerDashboardViewModel } from "../contracts/ownerDashboard";
import { confidenceText, rankText, scoreText } from "../lib/format";
import { humanizeCode, recommendationLabel } from "../lib/labels";
import { Chip, EvidenceClassChip, ReadinessChip, RecommendationChip } from "./Chips";
import { EconomicsPanel } from "./EconomicsPanel";

function ReasonList({ title, tone, codes }: { title: string; tone: "danger" | "caution" | "info"; codes: string[] }) {
  if (codes.length === 0) return null;
  return (
    <div className="space-y-1">
      <h4 className="flex items-center gap-2 text-xs font-medium text-zinc-300">
        {title} <Chip tone={tone}>{codes.length}</Chip>
      </h4>
      <ul className="space-y-0.5 text-sm text-zinc-300">
        {codes.map((code) => (
          <li key={code}>
            {humanizeCode(code)} <code className="text-[11px] text-zinc-400">{code}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceTable({ candidate }: { candidate: OwnerCandidate }) {
  if (candidate.evidence.length === 0) {
    return <p className="text-sm text-zinc-400">The provider supplied no evidence items for this candidate.</p>;
  }
  return (
    <div role="region" aria-label="Evidence provenance table" tabIndex={0} className="overflow-x-auto rounded-lg border border-white/[0.06]">
      <table className="w-full min-w-[26rem] text-sm">
        <caption className="sr-only">Evidence items behind this candidate, with class and freshness</caption>
        <thead className="border-b border-white/[0.06]">
          <tr>
            {["Area", "Status", "Class", "Freshness", "Source reference"].map((heading) => (
              <th key={heading} scope="col" className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-zinc-400">
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.04]">
          {candidate.evidence.map((item) => (
            <tr key={item.id}>
              <th scope="row" className="px-3 py-1.5 text-left font-normal text-zinc-200">
                {item.area ? humanizeCode(item.area) : "Unknown area"}
                {item.conflicting ? <span className="ml-2"><Chip tone="danger">Conflicts with other evidence</Chip></span> : null}
              </th>
              <td className="px-3 py-1.5 text-zinc-300">{item.status ? humanizeCode(item.status) : "Unknown"}</td>
              <td className="px-3 py-1.5"><EvidenceClassChip value={item.evidenceClass} /></td>
              <td className="px-3 py-1.5 text-zinc-300">{item.freshness ? humanizeCode(item.freshness) : "Unknown"}</td>
              <td className="px-3 py-1.5 text-xs text-zinc-400">{item.sourceRef ?? "Not provided"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CandidateDetail({
  candidate,
  saveToPortfolio,
  focusToken,
}: {
  candidate: OwnerCandidate;
  saveToPortfolio: OwnerDashboardViewModel["saveToPortfolio"];
  focusToken: number;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focusToken > 0) headingRef.current?.focus();
  }, [focusToken]);

  const noReasons =
    candidate.fatalGates.length === 0 && candidate.blockers.length === 0 && candidate.evidenceGaps.length === 0;
  const synthesisOverridden =
    candidate.readiness !== "ready" && candidate.synthesisRecommendation !== null;

  return (
    <section
      id="owner-candidate-detail"
      aria-labelledby="owner-detail-heading"
      className="space-y-5 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
    >
      <div className="space-y-2">
        <h2 id="owner-detail-heading" ref={headingRef} tabIndex={-1} className="text-base font-semibold text-zinc-100 outline-none focus-visible:outline-2">
          {candidate.name}
        </h2>
        <p className="text-xs text-zinc-400">
          {candidate.candidateId}
          {candidate.category ? ` · ${candidate.category}` : ""}
          {candidate.offeringKind ? ` · ${humanizeCode(candidate.offeringKind)}` : ""}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone={candidate.rank === null ? "muted" : "info"}>{candidate.rank === null ? "Not ranked" : `Rank ${rankText(candidate.rank)}`}</Chip>
          <RecommendationChip value={candidate.recommendation} />
          <ReadinessChip readiness={candidate.readiness} />
        </div>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <dt className="text-[11px] text-zinc-400">Provider score</dt>
            <dd className="text-zinc-100">{scoreText(candidate.synthesisScore)}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-zinc-400">Evidence confidence</dt>
            <dd className="text-zinc-100">{confidenceText(candidate.evidenceConfidence)}</dd>
            <dd className="text-[11px] text-zinc-400">share of evidence items marked as observed fact</dd>
          </div>
        </dl>
        <p className="text-xs text-zinc-400">
          Advisory only. “{recommendationLabel(candidate.recommendation)}” is a research recommendation, not launch
          authorization, and it takes no action in Shopify or anywhere else.
        </p>
        {synthesisOverridden ? (
          <p className="text-xs text-amber-300">
            The opportunity-synthesis component suggests “{humanizeCode(candidate.synthesisRecommendation as string)}”, but
            this candidate is not research-ready, so the evidence status above takes precedence.
          </p>
        ) : null}
        {candidate.providerClaimedExternalAction ? (
          <p role="alert" className="text-xs text-rose-300">
            The provider claimed an external action was allowed for this candidate. That claim is ignored here.
          </p>
        ) : null}
      </div>

      <section aria-labelledby="owner-why-heading" className="space-y-3">
        <h3 id="owner-why-heading" className="text-sm font-semibold text-zinc-100">Why this status</h3>
        <ReasonList title="Fatal gates" tone="danger" codes={candidate.fatalGates} />
        <ReasonList title="Blockers" tone="caution" codes={candidate.blockers} />
        <ReasonList title="Evidence gaps" tone="info" codes={candidate.evidenceGaps} />
        {noReasons ? (
          <p className="text-sm text-zinc-400">The provider reported no fatal gates, blockers, or evidence gaps.</p>
        ) : null}
      </section>

      <section aria-labelledby="owner-next-heading" className="space-y-1.5">
        <h3 id="owner-next-heading" className="text-sm font-semibold text-zinc-100">Next evidence to collect</h3>
        {candidate.nextEvidence.length > 0 ? (
          <ul className="list-inside list-disc text-sm text-zinc-300">
            {candidate.nextEvidence.map((item) => (
              <li key={item}>{humanizeCode(item)}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-400">The provider named no further evidence.</p>
        )}
        <p className="text-xs text-zinc-400">No external action is authorized by this list.</p>
      </section>

      <section aria-labelledby="owner-provenance-heading" className="space-y-2">
        <h3 id="owner-provenance-heading" className="text-sm font-semibold text-zinc-100">Evidence provenance</h3>
        <EvidenceTable candidate={candidate} />
      </section>

      <EconomicsPanel key={candidate.candidateId} candidate={candidate} />

      <div className="space-y-1.5 border-t border-white/[0.06] pt-4">
        <button
          type="button"
          disabled
          aria-describedby="owner-save-reason"
          className="inline-flex max-w-full cursor-not-allowed items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-left text-sm font-medium text-zinc-400"
        >
          <Lock aria-hidden="true" className="h-4 w-4" />
          Save to portfolio (not connected)
        </button>
        <p id="owner-save-reason" className="text-xs text-zinc-400">{saveToPortfolio.reason}</p>
      </div>
    </section>
  );
}
