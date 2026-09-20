import { useEffect, useMemo, useRef, type KeyboardEvent } from "react";
import {
  CANDIDATE_WINDOW_SIZE,
  type RankedCandidateRow,
} from "../contracts/firstPhaseEvidencePacket";
import { adjacentCandidateIndex, shouldHandoffDetailFocus } from "../lib/keyboardNav";
import {
  ensureSelectionInWindow,
  nextWindowStart,
  windowCandidates,
} from "../lib/windowCandidates";

function formatPct(value: number | null): string {
  return value !== null ? `${(value * 100).toFixed(0)}%` : "—";
}

function pillarLookup(candidate: RankedCandidateRow) {
  let market = null;
  let supplier = null;
  let economics = null;
  let attention = null;
  for (const cell of candidate.pillarCells) {
    if (cell.pillarId === "market_evidence") market = cell;
    else if (cell.pillarId === "supplier_feasibility") supplier = cell;
    else if (cell.pillarId === "economics") economics = cell;
    else if (cell.pillarId === "consumer_attention") attention = cell;
  }
  return { market, supplier, economics, attention };
}

export function RankedCandidatesPanel({
  candidates,
  selectedId,
  onSelect,
  windowStart,
  onWindowStartChange,
}: {
  candidates: RankedCandidateRow[];
  selectedId: string | null;
  onSelect: (candidateId: string) => void;
  windowStart: number;
  onWindowStartChange: (start: number) => void;
}) {
  const tbodyRef = useRef<HTMLTableSectionElement>(null);
  const detailFocusRequested = useRef(false);

  const alignedStart = useMemo(
    () => ensureSelectionInWindow(candidates, selectedId, windowStart, CANDIDATE_WINDOW_SIZE),
    [candidates, selectedId, windowStart],
  );

  useEffect(() => {
    if (alignedStart !== windowStart) onWindowStartChange(alignedStart);
  }, [alignedStart, windowStart, onWindowStartChange]);

  const windowed = useMemo(
    () => windowCandidates(candidates, alignedStart, CANDIDATE_WINDOW_SIZE),
    [candidates, alignedStart],
  );

  useEffect(() => {
    if (!selectedId || !detailFocusRequested.current) return;
    detailFocusRequested.current = false;
    const detail = document.getElementById("candidate-detail-panel");
    detail?.focus();
  }, [selectedId]);

  if (!candidates.length) {
    return (
      <section
        id="ranked-candidates-table"
        tabIndex={-1}
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

  function focusRow(absoluteIndex: number) {
    const button = tbodyRef.current?.querySelector<HTMLElement>(
      `button[data-candidate-index="${absoluteIndex}"]`,
    );
    button?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, absoluteIndex: number) {
    if (shouldHandoffDetailFocus(event.key)) {
      event.preventDefault();
      detailFocusRequested.current = true;
      onSelect(candidates[absoluteIndex].candidateId);
      return;
    }
    const nextIndex = adjacentCandidateIndex(candidates.length, absoluteIndex, event.key);
    if (nextIndex === absoluteIndex || nextIndex < 0) return;
    event.preventDefault();
    onSelect(candidates[nextIndex].candidateId);
    if (event.key === "Home") onWindowStartChange(0);
    else if (event.key === "End") {
      onWindowStartChange(Math.max(0, nextIndex - CANDIDATE_WINDOW_SIZE + 1));
    } else if (nextIndex >= windowed.windowStart + windowed.windowSize) {
      onWindowStartChange(nextWindowStart(windowed, "forward"));
    } else if (nextIndex < windowed.windowStart) {
      onWindowStartChange(nextWindowStart(windowed, "back"));
    }
    queueMicrotask(() => focusRow(nextIndex));
  }

  const activeId = selectedId ?? windowed.visible[0]?.candidateId ?? null;

  return (
    <section
      id="ranked-candidates-table"
      tabIndex={-1}
      className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
      aria-label="Ranked candidates"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-100" id="ranked-candidates-heading">
          Ranked candidates (server order)
        </h3>
        <p className="text-[11px] text-zinc-400">
          Arrow keys · Home/End · Enter opens detail · window {windowed.windowStart + 1}–
          {Math.min(windowed.windowStart + windowed.visible.length, windowed.total)} of {windowed.total}
        </p>
      </div>

      {(windowed.hasMoreBefore || windowed.hasMoreAfter) && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!windowed.hasMoreBefore}
            onClick={() => onWindowStartChange(nextWindowStart(windowed, "back"))}
            className="min-h-8 rounded border border-zinc-700 px-3 py-2 text-[11px] text-zinc-300 enabled:hover:border-zinc-500 disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-indigo-400"
          >
            Previous {CANDIDATE_WINDOW_SIZE}
          </button>
          <button
            type="button"
            disabled={!windowed.hasMoreAfter}
            onClick={() => onWindowStartChange(nextWindowStart(windowed, "forward"))}
            className="min-h-8 rounded border border-zinc-700 px-3 py-2 text-[11px] text-zinc-300 enabled:hover:border-zinc-500 disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-indigo-400"
          >
            Next {CANDIDATE_WINDOW_SIZE}
          </button>
        </div>
      )}

      {/* Mobile card list */}
      <ul
        className="mt-3 space-y-2 md:hidden"
        aria-labelledby="ranked-candidates-heading"
      >
        {windowed.visible.map((candidate, relativeIndex) => {
          const absoluteIndex = windowed.windowStart + relativeIndex;
          const selected = candidate.candidateId === selectedId;
          const { market, supplier } = pillarLookup(candidate);
          return (
            <li key={candidate.candidateId}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => {
                  detailFocusRequested.current = true;
                  onSelect(candidate.candidateId);
                }}
                className={`w-full rounded border p-3 text-left text-xs outline-none focus-visible:ring-1 focus-visible:ring-indigo-400 ${
                  selected
                    ? "border-indigo-500/40 bg-indigo-500/10"
                    : "border-zinc-800 bg-zinc-950/40"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-zinc-100">
                    #{candidate.rankIndex + 1} {candidate.title}
                  </span>
                  <span className="text-zinc-400">{candidate.riskLevel ?? "—"}</span>
                </div>
                <p className="mt-1 text-zinc-400">
                  Evidence {formatPct(candidate.evidenceCompleteness)} · Market{" "}
                  {formatPct(market?.score ?? candidate.competitionScore)} · Supplier{" "}
                  {formatPct(supplier?.score ?? candidate.supplierScore)}
                </p>
                <p className="mt-1 text-[11px] text-zinc-400">
                  {candidate.sku ?? "no sku"} · {candidate.evidenceClass.replace(/_/g, " ")} ·{" "}
                  {candidate.promotionState.replace(/_/g, " ")} ·{" "}
                  {candidate.nextBestAction?.replace(/_/g, " ") ?? "no next action"}
                </p>
                <p className="mt-1 text-[11px] text-amber-200/90">
                  {(candidate.commercialReviewTags ?? []).join(" · ").replace(/_/g, " ") || "review tags unavailable"}
                </p>
                <span className="sr-only">Absolute index {absoluteIndex}</span>
              </button>
            </li>
          );
        })}
      </ul>

      <div
        className="mt-3 hidden overflow-x-auto md:block"
        tabIndex={0}
        role="region"
        aria-label="Scrollable ranked candidates table"
      >
        <table
          className="min-w-full text-left text-xs"
          aria-labelledby="ranked-candidates-heading"
        >
          <caption className="sr-only">
            Server-ordered first-phase candidates with pillar-level evidence scores. Selection is read-only.
            Showing a bounded window of {CANDIDATE_WINDOW_SIZE} rows for performance.
          </caption>
          <thead className="text-zinc-400">
            <tr>
              {[
                "Rank",
                "Candidate",
                "SKU",
                "Evidence",
                "Market",
                "Supplier",
                "Economics",
                "Attention",
                "Class",
                "Promotion",
                "Next action",
                "Decision",
                "Risk",
                "Review",
              ].map((heading) => (
                <th key={heading} scope="col" className="px-2 py-1.5 font-medium">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody ref={tbodyRef}>
            {windowed.visible.map((candidate, relativeIndex) => {
              const absoluteIndex = windowed.windowStart + relativeIndex;
              const selected = candidate.candidateId === selectedId;
              const { market, supplier, economics, attention } = pillarLookup(candidate);
              const tabIndex = candidate.candidateId === activeId ? 0 : -1;
              return (
                <tr
                  key={candidate.candidateId}
                  className={`border-t border-zinc-800 text-zinc-300 ${
                    selected ? "bg-indigo-500/10" : "hover:bg-zinc-800/40"
                  }`}
                >
                  <td className="px-2 py-2">{candidate.rankIndex + 1}</td>
                  <th scope="row" className="px-2 py-2 font-medium">
                    <button
                      type="button"
                      data-candidate-index={absoluteIndex}
                      tabIndex={tabIndex}
                      aria-pressed={selected}
                      className="block w-full rounded text-left text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
                      onClick={() => {
                        detailFocusRequested.current = true;
                        onSelect(candidate.candidateId);
                      }}
                      onKeyDown={(event) => handleKeyDown(event, absoluteIndex)}
                    >
                      {candidate.title}
                      {candidate.isTopCandidate && (
                        <span className="ml-2 rounded border border-indigo-500/30 px-1 text-[10px] text-indigo-300">
                          top
                        </span>
                      )}
                      <span className="block text-[10px] font-normal text-zinc-400">{candidate.candidateId}</span>
                    </button>
                  </th>
                  <td className="px-2 py-2 font-mono text-[11px] text-zinc-400">{candidate.sku ?? "—"}</td>
                  <td className="px-2 py-2">{formatPct(candidate.evidenceCompleteness)}</td>
                  <td className="px-2 py-2">
                    <span>
                      {formatPct(market?.score ?? candidate.competitionScore)}
                    </span>
                    {market?.detail ? (
                      <span className="block text-[10px] text-zinc-400">{market.detail}</span>
                    ) : null}
                  </td>
                  <td className="px-2 py-2">
                    <span>
                      {formatPct(supplier?.score ?? candidate.supplierScore)}
                    </span>
                    {supplier?.detail ? (
                      <span className="block text-[10px] text-zinc-400">{supplier.detail}</span>
                    ) : null}
                  </td>
                  <td className="px-2 py-2">
                    <span>{candidate.economicsLabel ?? "—"}</span>
                    {economics?.detail ? (
                      <span className="block text-[10px] text-zinc-400">{economics.detail}</span>
                    ) : null}
                  </td>
                  <td className="px-2 py-2 text-zinc-400">{attention?.status ?? "unavailable"}</td>
                  <td className="px-2 py-2">{candidate.evidenceClass.replace(/_/g, " ")}</td>
                  <td className="px-2 py-2">{candidate.promotionState.replace(/_/g, " ")}</td>
                  <td className="px-2 py-2">{candidate.nextBestAction?.replace(/_/g, " ") ?? "—"}</td>
                  <td className="px-2 py-2">{candidate.commercialDecision?.replace(/_/g, " ") ?? "—"}</td>
                  <td className="px-2 py-2">{candidate.riskLevel ?? "—"}</td>
                  <td className="px-2 py-2 text-[10px] text-zinc-400">
                    {(candidate.commercialReviewTags ?? []).slice(0, 3).join(" · ").replace(/_/g, " ") || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
