import { useRef, type KeyboardEvent } from "react";
import type { DroppedRow, OpportunityRow } from "../contracts/ownerResearch";
import { formatReportedScore, humanize } from "../lib/format";
import { resolveListboxKey } from "../lib/listboxKeys";
import { describeHiddenRows } from "../lib/stateCopy";

export const OPPORTUNITY_DETAIL_ID = "owner-opportunity-detail";
const LISTBOX_HINT_ID = "owner-ranked-hint";
const CHIP_PILLARS = new Set(["market_evidence", "supplier_feasibility", "economics", "consumer_attention"]);

const JUMP_LINK =
  "mt-2 inline-flex min-h-[44px] items-center rounded text-sm text-sky-300 underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400 lg:hidden";
const CHIP = "inline-flex items-center rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[11px] text-zinc-200";

function freshnessChip(row: OpportunityRow): string {
  switch (row.freshness.status) {
    case "fresh": return "Fresh";
    case "stale": return "Stale";
    case "invalid": return "Freshness invalid";
    default: return "Freshness not reported";
  }
}

/**
 * Screen-reader summary. The option's children are presentational, so this
 * carries the state; the candidate id is exposed as the option's description
 * (aria-describedby) so a long id is not re-read as part of every name.
 */
export function describeOption(row: OpportunityRow): string {
  const gates = row.hardGates.length;
  const parts = [
    `Rank ${row.rankNumber ?? `position ${row.position}`}`,
    row.title ?? "Untitled candidate",
    `evidence ${humanize(row.provenance.evidenceClass)}`,
  ];
  if (row.partial) parts.push("partial evidence");
  if (gates > 0) parts.push(`${gates} blocking ${gates === 1 ? "gate" : "gates"}`);
  if (row.inPortfolio === true) parts.push("in curated portfolio");
  parts.push(freshnessChip(row).toLowerCase());
  return parts.join(", ");
}

/**
 * Backend-ordered ranked candidates as a single-select listbox.
 * Keys: ArrowUp/ArrowDown/Home/End move the selection and focus; Enter or Space
 * hands focus to the details region. Order is never re-sorted by score.
 */
export function RankedOpportunityList({
  rows,
  selectedId,
  onSelect,
  onActivate,
  hiddenRows,
}: {
  rows: readonly OpportunityRow[];
  selectedId: string | null;
  onSelect: (candidateId: string) => void;
  onActivate?: (candidateId: string) => void;
  /** Rows the adapter dropped (duplicate/malformed ids, rows past the cap); named here so a candidate never vanishes silently. */
  hiddenRows?: readonly DroppedRow[];
}) {
  const optionRefs = useRef<Array<HTMLLIElement | null>>([]);
  if (rows.length === 0) return null;
  const hidden = describeHiddenRows(hiddenRows ?? []);

  const found = rows.findIndex((row) => row.candidateId === selectedId);
  const activeIndex = found >= 0 ? found : 0;

  function handleKeyDown(event: KeyboardEvent<HTMLLIElement>, index: number) {
    const action = resolveListboxKey(event, index, rows.length);
    if (!action.handled) return;
    event.preventDefault();
    if (action.kind === "activate") {
      onActivate?.(rows[index].candidateId);
    } else if (action.kind === "move") {
      const next = action.nextIndex;
      onSelect(rows[next].candidateId);
      queueMicrotask(() => optionRefs.current[next]?.focus());
    }
  }

  return (
    <section aria-labelledby="owner-ranked-heading" className="min-w-0 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 sm:p-4 lg:sticky lg:top-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="owner-ranked-heading" className="text-base font-semibold text-zinc-100">Ranked opportunities</h2>
        <p className="text-xs text-zinc-400">{rows.length} in backend order</p>
      </div>
      <p id={LISTBOX_HINT_ID} className="mt-1 text-xs text-zinc-400">
        Arrow keys move the selection; Home and End jump to the first and last candidate; Enter opens the details.
      </p>
      {hidden.total > 0 ? (
        <p data-hidden-rows={hidden.total} className="mt-1 text-xs text-amber-200 [overflow-wrap:anywhere]">
          {hidden.total} ranked row{hidden.total === 1 ? "" : "s"} not shown: {hidden.text}. Each is listed in the ranking details above.
        </p>
      ) : null}
      <a href={`#${OPPORTUNITY_DETAIL_ID}`} className={JUMP_LINK}>
        Jump to selected candidate details
      </a>
      <ul
        role="listbox"
        aria-labelledby="owner-ranked-heading"
        aria-describedby={LISTBOX_HINT_ID}
        aria-orientation="vertical"
        className="mt-3 space-y-2 lg:max-h-[70vh] lg:overflow-y-auto lg:p-1"
      >
        {rows.map((row, index) => {
          const selected = index === activeIndex;
          return (
            <li
              key={row.candidateId}
              id={`owner-opp-option-${index}`}
              role="option"
              aria-selected={selected}
              aria-label={describeOption(row)}
              aria-describedby={`owner-opp-id-${index}`}
              tabIndex={selected ? 0 : -1}
              data-candidate-id={row.candidateId}
              ref={(element) => {
                optionRefs.current[index] = element;
              }}
              onClick={() => onSelect(row.candidateId)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              className={`min-h-[44px] cursor-pointer rounded-lg border p-3 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400 ${
                selected ? "border-sky-400 bg-sky-500/10" : "border-zinc-800 bg-zinc-950/40 hover:border-zinc-600"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className="shrink-0 rounded bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-100">
                  {row.rankNumber !== null ? `#${row.rankNumber}` : `pos ${row.position}`}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium [overflow-wrap:anywhere]">{row.title ?? "Untitled candidate"}</p>
                  <p id={`owner-opp-id-${index}`} className="font-mono text-[11px] text-zinc-400 [overflow-wrap:anywhere]">{row.candidateId}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className={CHIP}>Evidence: {humanize(row.provenance.evidenceClass)}</span>
                    <span className={CHIP}>{freshnessChip(row)}</span>
                    {row.partial ? <span className={CHIP}>Partial evidence</span> : null}
                    {row.hardGates.length > 0 ? <span className={CHIP}>Blocking gates: {row.hardGates.length}</span> : null}
                    {row.inPortfolio === true ? <span className={`${CHIP} border-emerald-500/60 text-emerald-200`}>In portfolio</span> : null}
                  </div>
                  <div className="mt-1.5 hidden flex-wrap gap-1.5 sm:flex">
                    {row.pillars
                      .filter((pillar) => CHIP_PILLARS.has(pillar.id))
                      .map((pillar) => (
                        <span key={pillar.id} className={CHIP}>
                          {pillar.label}: {pillar.score !== null ? formatReportedScore(pillar.score) : humanize(pillar.status)}
                        </span>
                      ))}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      <a href={`#${OPPORTUNITY_DETAIL_ID}`} className={JUMP_LINK}>
        Jump to selected candidate details
      </a>
    </section>
  );
}
