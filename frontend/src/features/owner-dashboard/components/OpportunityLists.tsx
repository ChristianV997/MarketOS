import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { OwnerCandidate } from "../contracts/ownerDashboard";
import { confidenceText, evidenceStatusText, rankText, scoreText } from "../lib/format";
import { UNRANKED_LABELS } from "../lib/labels";
import { nextRowIndex } from "../lib/rowNavigation";
import { EvidenceClassChip, RecommendationChip } from "./Chips";

function ScrollRegion({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="overflow-x-auto rounded-xl border border-white/[0.06]"
    >
      {children}
    </div>
  );
}

const TH = "px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-zinc-400";
const TD = "px-3 py-2.5 align-top text-sm text-zinc-300";

function SelectButton({
  candidate,
  selected,
  onSelect,
  onKeyDown,
}: {
  candidate: OwnerCandidate;
  selected: boolean;
  onSelect: (candidateId: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <>
      <button
        type="button"
        data-candidate-id={candidate.candidateId}
        aria-pressed={selected}
        onClick={() => onSelect(candidate.candidateId)}
        onKeyDown={onKeyDown}
        className="rounded text-left font-medium text-zinc-100 underline-offset-2 hover:underline"
      >
        {candidate.name}
      </button>
      <div className="text-xs text-zinc-400">
        {candidate.candidateId}
        {candidate.category ? ` · ${candidate.category}` : ""}
      </div>
    </>
  );
}

function EvidenceCell({ candidate }: { candidate: OwnerCandidate }) {
  return (
    <div className="space-y-1">
      <div>{evidenceStatusText(candidate)}</div>
      <div className="flex flex-wrap gap-1">
        {candidate.evidenceClasses.map((value) => (
          <EvidenceClassChip key={value} value={value} />
        ))}
      </div>
    </div>
  );
}

export function OpportunityLists({
  ranked,
  unranked,
  selectedId,
  onSelect,
}: {
  ranked: OwnerCandidate[];
  unranked: OwnerCandidate[];
  selectedId: string | null;
  onSelect: (candidateId: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const buttons = Array.from(rootRef.current?.querySelectorAll<HTMLButtonElement>("button[data-candidate-id]") ?? []);
    const current = buttons.indexOf(event.currentTarget);
    const next = nextRowIndex(current, event.key, buttons.length);
    if (next === null || next === current) return;
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <div ref={rootRef} className="space-y-6">
      <section aria-labelledby="owner-ranked-heading" className="space-y-2">
        <h2 id="owner-ranked-heading" className="text-sm font-semibold text-zinc-100">
          Ranked opportunities
        </h2>
        <p className="text-xs text-zinc-400">
          The provider's own order. It ranks only candidates that are research-ready and scored, and this page never
          re-sorts or re-scores them.
        </p>
        {ranked.length === 0 ? (
          <p className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-sm text-zinc-400">
            No candidate is ranked yet. See the reasons below.
          </p>
        ) : (
          <ScrollRegion label="Ranked opportunities table">
            <table className="w-full min-w-[34rem]">
              <caption className="sr-only">Ranked opportunities in the provider's order</caption>
              <thead className="border-b border-white/[0.06]">
                <tr>
                  <th scope="col" className={TH}>Rank</th>
                  <th scope="col" className={TH}>Opportunity</th>
                  <th scope="col" className={TH}>Recommendation</th>
                  <th scope="col" className={TH}>Provider score</th>
                  <th scope="col" className={TH}>Evidence confidence</th>
                  <th scope="col" className={TH}>Evidence status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {ranked.map((candidate) => (
                  <tr key={candidate.candidateId} className={cn(candidate.candidateId === selectedId && "bg-white/[0.05]")}>
                    <td className={cn(TD, "font-semibold text-zinc-100")}>{rankText(candidate.rank)}</td>
                    <th scope="row" className={cn(TD, "text-left font-normal")}>
                      <SelectButton
                        candidate={candidate}
                        selected={candidate.candidateId === selectedId}
                        onSelect={onSelect}
                        onKeyDown={handleKeyDown}
                      />
                    </th>
                    <td className={TD}><RecommendationChip value={candidate.recommendation} /></td>
                    <td className={TD}>{scoreText(candidate.synthesisScore)}</td>
                    <td className={TD}>{confidenceText(candidate.evidenceConfidence)}</td>
                    <td className={TD}><EvidenceCell candidate={candidate} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </section>

      {unranked.length > 0 ? (
        <section aria-labelledby="owner-unranked-heading" className="space-y-2">
          <h2 id="owner-unranked-heading" className="text-sm font-semibold text-zinc-100">
            Not ranked
          </h2>
          <p className="text-xs text-zinc-400">
            A score alone does not earn a rank: candidates with evidence gaps or fatal gates are shown here, with the
            provider's reason, in the provider's order.
          </p>
          <ScrollRegion label="Not ranked opportunities table">
            <table className="w-full min-w-[34rem]">
              <caption className="sr-only">Opportunities the provider did not rank, with the reason</caption>
              <thead className="border-b border-white/[0.06]">
                <tr>
                  <th scope="col" className={TH}>Opportunity</th>
                  <th scope="col" className={TH}>Why not ranked</th>
                  <th scope="col" className={TH}>Recommendation</th>
                  <th scope="col" className={TH}>Provider score</th>
                  <th scope="col" className={TH}>Evidence status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {unranked.map((candidate) => (
                  <tr key={candidate.candidateId} className={cn(candidate.candidateId === selectedId && "bg-white/[0.05]")}>
                    <th scope="row" className={cn(TD, "text-left font-normal")}>
                      <SelectButton
                        candidate={candidate}
                        selected={candidate.candidateId === selectedId}
                        onSelect={onSelect}
                        onKeyDown={handleKeyDown}
                      />
                    </th>
                    <td className={TD}>{candidate.unrankedReason ? UNRANKED_LABELS[candidate.unrankedReason] : "Not ranked"}</td>
                    <td className={TD}><RecommendationChip value={candidate.recommendation} /></td>
                    <td className={TD}>{scoreText(candidate.synthesisScore)}</td>
                    <td className={TD}><EvidenceCell candidate={candidate} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        </section>
      ) : null}
    </div>
  );
}
