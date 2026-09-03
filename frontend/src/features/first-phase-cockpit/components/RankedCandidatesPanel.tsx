import type { KeyboardEvent } from "react";
import type { RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket";

function formatPct(value: number | null): string {
  return value !== null ? `${(value * 100).toFixed(0)}%` : "—";
}

export function RankedCandidatesPanel({
  candidates,
  selectedId,
  onSelect,
}: {
  candidates: RankedCandidateRow[];
  selectedId: string | null;
  onSelect: (candidateId: string) => void;
}) {
  if (!candidates.length) {
    return (
      <section
        className="rounded-lg border border-dashed border-zinc-700 bg-zinc-900/30 p-6 text-sm text-zinc-400"
        aria-label="Ranked candidates empty"
      >
        <h3 className="text-sm font-medium text-zinc-300">No ranked candidates</h3>
        <p className="mt-2">
          No candidates matched the current filters, or the benchmark matrix returned an empty list.
          The frontend preserves backend order only and never invents rankings.
        </p>
      </section>
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTableRowElement>, index: number) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(candidates[index].candidateId);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = candidates[Math.min(index + 1, candidates.length - 1)];
      onSelect(next.candidateId);
      (event.currentTarget.parentElement?.children[index + 1] as HTMLElement | undefined)?.focus();
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      const prev = candidates[Math.max(index - 1, 0)];
      onSelect(prev.candidateId);
      (event.currentTarget.parentElement?.children[index - 1] as HTMLElement | undefined)?.focus();
    }
  }

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4" aria-label="Ranked candidates">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-100" id="ranked-candidates-heading">
          Ranked candidates (server order)
        </h3>
        <p className="text-[11px] text-zinc-500">Use arrow keys to move · Enter to open detail</p>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table
          id="ranked-candidates-table"
          className="min-w-full text-left text-xs"
          aria-labelledby="ranked-candidates-heading"
        >
          <caption className="sr-only">
            Server-ordered first-phase candidates with pillar-level evidence scores. Selection is read-only.
          </caption>
          <thead className="text-zinc-500">
            <tr>
              {[
                "Rank",
                "Candidate",
                "Evidence",
                "Market",
                "Supplier",
                "Economics",
                "Attention",
                "Mode",
                "Next action",
                "Decision",
                "Risk",
              ].map((heading) => (
                <th key={heading} scope="col" className="px-2 py-1.5 font-medium">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate, index) => {
              const selected = candidate.candidateId === selectedId;
              const market = candidate.pillarCells.find((cell) => cell.pillarId === "market_evidence");
              const supplier = candidate.pillarCells.find((cell) => cell.pillarId === "supplier_feasibility");
              const economics = candidate.pillarCells.find((cell) => cell.pillarId === "economics");
              const attention = candidate.pillarCells.find((cell) => cell.pillarId === "consumer_attention");
              return (
                <tr
                  key={candidate.candidateId}
                  tabIndex={0}
                  aria-selected={selected}
                  onClick={() => onSelect(candidate.candidateId)}
                  onKeyDown={(event) => handleKeyDown(event, index)}
                  className={`cursor-pointer border-t border-zinc-800 text-zinc-300 outline-none focus-visible:bg-indigo-500/10 focus-visible:ring-1 focus-visible:ring-indigo-400 ${
                    selected ? "bg-indigo-500/10" : "hover:bg-zinc-800/40"
                  }`}
                >
                  <td className="px-2 py-2">{candidate.rankIndex + 1}</td>
                  <td className="px-2 py-2">
                    <span className="font-medium text-zinc-100">{candidate.title}</span>
                    {candidate.isTopCandidate && (
                      <span className="ml-2 rounded border border-indigo-500/30 px-1 text-[10px] text-indigo-300">
                        top
                      </span>
                    )}
                    <div className="text-[10px] text-zinc-500">{candidate.candidateId}</div>
                  </td>
                  <td className="px-2 py-2">{formatPct(candidate.evidenceCompleteness)}</td>
                  <td className="px-2 py-2">
                    <span title={market?.detail ?? undefined}>{formatPct(market?.score ?? candidate.competitionScore)}</span>
                  </td>
                  <td className="px-2 py-2">
                    <span title={supplier?.detail ?? undefined}>{formatPct(supplier?.score ?? candidate.supplierScore)}</span>
                  </td>
                  <td className="px-2 py-2">
                    <span title={economics?.detail ?? undefined}>{candidate.economicsLabel ?? "—"}</span>
                  </td>
                  <td className="px-2 py-2 text-zinc-500">{attention?.status ?? "unavailable"}</td>
                  <td className="px-2 py-2">{candidate.evidenceMode.replace(/_/g, " ")}</td>
                  <td className="px-2 py-2">{candidate.nextBestAction?.replace(/_/g, " ") ?? "—"}</td>
                  <td className="px-2 py-2">{candidate.commercialDecision?.replace(/_/g, " ") ?? "—"}</td>
                  <td className="px-2 py-2">{candidate.riskLevel ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
