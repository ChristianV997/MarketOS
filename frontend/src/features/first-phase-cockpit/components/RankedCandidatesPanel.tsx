import type { RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket";

export function RankedCandidatesPanel({ candidates }: { candidates: RankedCandidateRow[] }) {
  if (!candidates.length) {
    return (
      <section className="rounded-lg border border-dashed border-zinc-700 bg-zinc-900/30 p-6 text-sm text-zinc-400">
        No ranked candidates returned by the benchmark matrix. The frontend preserves backend order only.
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4" aria-label="Ranked candidates">
      <h3 className="text-sm font-medium text-zinc-100">Ranked candidates (server order)</h3>
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="text-zinc-500">
            <tr>
              {["Rank", "Candidate", "Evidence", "Supplier", "Competition", "Economics", "Decision", "Risk"].map((heading) => (
                <th key={heading} className="px-2 py-1.5 font-medium">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.candidateId} className="border-t border-zinc-800 text-zinc-300">
                <td className="px-2 py-2">{candidate.rankIndex + 1}</td>
                <td className="px-2 py-2">
                  {candidate.title}
                  {candidate.isTopCandidate && (
                    <span className="ml-2 rounded border border-indigo-500/30 px-1 text-[10px] text-indigo-300">
                      top
                    </span>
                  )}
                </td>
                <td className="px-2 py-2">
                  {candidate.evidenceCompleteness !== null
                    ? `${(candidate.evidenceCompleteness * 100).toFixed(0)}%`
                    : "—"}
                </td>
                <td className="px-2 py-2">
                  {candidate.supplierScore !== null ? `${(candidate.supplierScore * 100).toFixed(0)}%` : "—"}
                </td>
                <td className="px-2 py-2">
                  {candidate.competitionScore !== null ? `${(candidate.competitionScore * 100).toFixed(0)}%` : "—"}
                </td>
                <td className="px-2 py-2">{candidate.economicsLabel ?? "—"}</td>
                <td className="px-2 py-2">{candidate.commercialDecision?.replace(/_/g, " ") ?? "—"}</td>
                <td className="px-2 py-2">{candidate.riskLevel ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
