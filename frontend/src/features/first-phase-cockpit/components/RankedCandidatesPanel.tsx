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
  const mobileListRef = useRef<HTMLUListElement>(null);
  const detailFocusRequested = useRef(false);
  const pendingFocusCandidateId = useRef<string | null>(null);

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
    queueMicrotask(() => {
      const detail = document.getElementById("candidate-detail-panel");
      detail?.focus();
    });
  }, [selectedId]);

  useEffect(() => {
    if (!pendingFocusCandidateId.current) return;
    const targetId = pendingFocusCandidateId.current;
    const row = tbodyRef.current?.querySelector<HTMLElement>(`tr[data-candidate-id="${targetId}"]`);
    if (row) {
      pendingFocusCandidateId.current = null;
      row.focus();
      return;
    }
    const mobileButton = mobileListRef.current?.querySelector<HTMLElement>(`button[data-candidate-id="${targetId}"]`);
    if (mobileButton) {
      pendingFocusCandidateId.current = null;
      mobileButton.focus();
      return;
    }
  });

  if (!candidates.length) {
    return (
      <section
        id="ranked-candidates-table"
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
    const candidate = candidates[absoluteIndex];
    if (!candidate) return;
    const row = tbodyRef.current?.querySelector<HTMLElement>(`tr[data-candidate-id="${candidate.candidateId}"]`);
    if (row) {
      pendingFocusCandidateId.current = null;
      row.focus();
      return;
    }
    const mobileButton = mobileListRef.current?.querySelector<HTMLElement>(`button[data-candidate-id="${candidate.candidateId}"]`);
    if (mobileButton) {
      pendingFocusCandidateId.current = null;
      mobileButton.focus();
      return;
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>, absoluteIndex: number) {
    if (shouldHandoffDetailFocus(event.key)) {
      event.preventDefault();
      detailFocusRequested.current = true;
      onSelect(candidates[absoluteIndex].candidateId);
      if (selectedId === candidates[absoluteIndex].candidateId) {
        detailFocusRequested.current = false;
        queueMicrotask(() => {
          document.getElementById("candidate-detail-panel")?.focus();
        });
      }
      return;
    }
    const nextIndex = adjacentCandidateIndex(candidates.length, absoluteIndex, event.key);
    if (nextIndex === absoluteIndex || nextIndex < 0) return;
    event.preventDefault();
    const nextCandidate = candidates[nextIndex];
    if (nextCandidate) {
      pendingFocusCandidateId.current = nextCandidate.candidateId;
    }
    onSelect(candidates[nextIndex].candidateId);
    if (event.key === "Home") {
      onWindowStartChange(0);
    } else if (event.key === "End") {
      onWindowStartChange(Math.max(0, nextIndex - CANDIDATE_WINDOW_SIZE + 1));
    } else if (event.key === "ArrowDown" && nextIndex >= windowed.windowStart + windowed.windowSize) {
      onWindowStartChange(nextWindowStart(windowed, "forward"));
    } else if (event.key === "ArrowUp" && nextIndex < windowed.windowStart) {
      onWindowStartChange(nextWindowStart(windowed, "back"));
    }
    queueMicrotask(() => focusRow(nextIndex));
  }

  const activeId = selectedId ?? windowed.visible[0]?.candidateId ?? null;

  return (
    <section
      id="ranked-candidates-table"
      className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4"
      aria-label="Ranked candidates"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-100" id="ranked-candidates-heading">
          Ranked candidates (server order)
        </h3>
        <p className="text-[11px] text-zinc-500">
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
        ref={mobileListRef}
        className="mt-3 space-y-2 md:hidden"
        role="listbox"
        aria-labelledby="ranked-candidates-heading"
        aria-label="Ranked candidates mobile list"
      >
        {windowed.visible.map((candidate, relativeIndex) => {
          const absoluteIndex = windowed.windowStart + relativeIndex;
          const selected = candidate.candidateId === selectedId;
          const { market, supplier } = pillarLookup(candidate);
          const tabIndex = candidate.candidateId === activeId ? 0 : -1;
          return (
            <li key={candidate.candidateId} role="presentation">
              <button
                type="button"
                data-candidate-id={candidate.candidateId}
                role="option"
                tabIndex={tabIndex}
                aria-selected={selected}
                aria-posinset={absoluteIndex + 1}
                aria-setsize={candidates.length}
                onClick={() => {
                  detailFocusRequested.current = true;
                  onSelect(candidate.candidateId);
                  if (selectedId === candidate.candidateId) {
                    detailFocusRequested.current = false;
                    queueMicrotask(() => {
                      document.getElementById("candidate-detail-panel")?.focus();
                    });
                  }
                }}
                onKeyDown={(event) => handleKeyDown(event, absoluteIndex)}
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
                  <span className="text-zinc-500">{candidate.riskLevel ?? "—"}</span>
                </div>
                <p className="mt-1 text-zinc-400">
                  Evidence {formatPct(candidate.evidenceCompleteness)} · Market{" "}
                  {formatPct(market?.score ?? candidate.competitionScore)} · Supplier{" "}
                  {formatPct(supplier?.score ?? candidate.supplierScore)}
                </p>
                <p className="mt-1 text-[11px] text-zinc-500">
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

      <div className="mt-3 hidden overflow-x-auto md:block">
        <table
          className="min-w-full text-left text-xs"
          aria-labelledby="ranked-candidates-heading"
          role="grid"
          aria-colcount={14}
          aria-rowcount={candidates.length + 1}
        >
          <caption className="sr-only">
            Server-ordered first-phase candidates with pillar-level evidence scores. Selection is read-only.
            Showing a bounded window of {CANDIDATE_WINDOW_SIZE} rows for performance.
          </caption>
          <thead className="text-zinc-500">
            <tr role="row">
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
                <th key={heading} scope="col" role="columnheader" className="px-2 py-1.5 font-medium">
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
                  data-candidate-id={candidate.candidateId}
                  role="row"
                  tabIndex={tabIndex}
                  aria-selected={selected}
                  aria-rowindex={absoluteIndex + 2}
                  onClick={() => {
                    detailFocusRequested.current = true;
                    onSelect(candidate.candidateId);
                    if (selectedId === candidate.candidateId) {
                      detailFocusRequested.current = false;
                      queueMicrotask(() => {
                        document.getElementById("candidate-detail-panel")?.focus();
                      });
                    }
                  }}
                  onKeyDown={(event) => handleKeyDown(event, absoluteIndex)}
                  className={`cursor-pointer border-t border-zinc-800 text-zinc-300 outline-none focus-visible:bg-indigo-500/10 focus-visible:ring-1 focus-visible:ring-indigo-400 ${
                    selected ? "bg-indigo-500/10" : "hover:bg-zinc-800/40"
                  }`}
                >
                  <td role="gridcell" className="px-2 py-2">{candidate.rankIndex + 1}</td>
                  <td role="gridcell" className="px-2 py-2">
                    <span className="font-medium text-zinc-100">{candidate.title}</span>
                    {candidate.isTopCandidate && (
                      <span className="ml-2 rounded border border-indigo-500/30 px-1 text-[10px] text-indigo-300">
                        top
                      </span>
                    )}
                    <div className="text-[10px] text-zinc-500">{candidate.candidateId}</div>
                  </td>
                  <td role="gridcell" className="px-2 py-2 font-mono text-[11px] text-zinc-400">{candidate.sku ?? "—"}</td>
                  <td role="gridcell" className="px-2 py-2">{formatPct(candidate.evidenceCompleteness)}</td>
                  <td role="gridcell" className="px-2 py-2">
                    <span title={market?.detail ?? undefined}>
                      {formatPct(market?.score ?? candidate.competitionScore)}
                    </span>
                  </td>
                  <td role="gridcell" className="px-2 py-2">
                    <span title={supplier?.detail ?? undefined}>
                      {formatPct(supplier?.score ?? candidate.supplierScore)}
                    </span>
                  </td>
                  <td role="gridcell" className="px-2 py-2">
                    <span title={economics?.detail ?? undefined}>{candidate.economicsLabel ?? "—"}</span>
                  </td>
                  <td role="gridcell" className="px-2 py-2 text-zinc-500">{attention?.status ?? "unavailable"}</td>
                  <td role="gridcell" className="px-2 py-2">{candidate.evidenceClass.replace(/_/g, " ")}</td>
                  <td role="gridcell" className="px-2 py-2">{candidate.promotionState.replace(/_/g, " ")}</td>
                  <td role="gridcell" className="px-2 py-2">{candidate.nextBestAction?.replace(/_/g, " ") ?? "—"}</td>
                  <td role="gridcell" className="px-2 py-2">{candidate.commercialDecision?.replace(/_/g, " ") ?? "—"}</td>
                  <td role="gridcell" className="px-2 py-2">{candidate.riskLevel ?? "—"}</td>
                  <td role="gridcell" className="px-2 py-2 text-[10px] text-zinc-400">
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
