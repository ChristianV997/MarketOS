import { useMemo, useState } from "react";
import type { SectionId } from "../contracts/researchSurface.ts";
import { adaptResearchSurface } from "../lib/adaptResearchSurface.ts";
import { composeResearchSurface, moveSelection } from "../lib/composeResearchSurface.ts";

export function ConsultingResearchSurface({
  packet,
  loading = false,
  errorMessage = null,
}: {
  packet: unknown;
  loading?: boolean;
  errorMessage?: string | null;
}) {
  const adapted = useMemo(() => adaptResearchSurface(packet), [packet]);
  const [selected, setSelected] = useState<SectionId | null>(null);
  const view = useMemo(() => composeResearchSurface({
    loading,
    errorMessage,
    model: adapted.model,
    rejected: adapted.rejected,
    selectedSectionId: selected,
  }), [adapted, errorMessage, loading, selected]);

  return (
    <section aria-labelledby="research-surface-heading" className="min-w-0 space-y-4 p-3 sm:p-4 text-zinc-100">
      <a href="#research-surface-table" className="sr-only focus:not-sr-only focus:rounded focus:bg-zinc-900 focus:px-3 focus:py-2">
        Skip to research sections
      </a>
      <header>
        <h1 id="research-surface-heading" tabIndex={-1} className="text-xl font-semibold outline-none">{view.model.display_name}</h1>
        <p className="text-sm text-zinc-300">{view.model.engagement_id} · {view.model.offering_kind}</p>
      </header>
      <div role="status" aria-live="polite" className="rounded border border-zinc-700 p-3 text-sm">{view.state} — {view.message}</div>
      <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable research section table">
        <table id="research-surface-table" className="min-w-[36rem] text-left text-sm">
          <thead>
            <tr>
              <th scope="col">Section</th>
              <th scope="col">Class</th>
              <th scope="col">Freshness</th>
              <th scope="col">Conflict</th>
              <th scope="col">Missing</th>
            </tr>
          </thead>
          <tbody>
            {view.model.sections.map((section) => (
              <tr key={section.section_id}>
                <th scope="row">
                  <button
                    type="button"
                    aria-pressed={section.section_id === view.selectedSectionId}
                    className="motion-reduce:transition-none rounded px-2 py-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
                    onClick={() => setSelected(section.section_id)}
                    onKeyDown={(event) => {
                      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
                      event.preventDefault();
                      setSelected(moveSelection(view.model.sections.map((item) => item.section_id), view.selectedSectionId, event.key));
                    }}
                  >
                    {section.title}
                  </button>
                </th>
                <td>{section.rows.map((row) => row.evidence_class).join(", ") || "unavailable"}</td>
                <td>{section.rows.some((row) => row.fresh === false) ? "stale" : "undated"}</td>
                <td>{section.rows.map((row) => row.conflict_note).filter(Boolean).join("; ") || "none"}</td>
                <td>{section.missing.join(", ") || "none listed"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section aria-label="Blockers and next action">
        <p>Blockers: {view.model.blockers.join("; ") || "none listed"}</p>
        <p>Next action, display only: {view.model.next_action}</p>
        <ul>{view.conflicts.map((item) => <li key={`${item.section_id}-${item.note}`}>{item.section_id}: {item.note}</li>)}</ul>
      </section>
      <pre tabIndex={0} className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-zinc-950 p-3 text-xs">
        {JSON.stringify(view.exportPreview.payload ?? { accepted: false, reason: view.exportPreview.reason }, null, 2)}
      </pre>
    </section>
  );
}
