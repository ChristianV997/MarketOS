import { useMemo, useState } from "react";
import type { SectionId } from "../contracts/consultingResearchReview.ts";
import { adaptConsultingResearch } from "../lib/adaptConsultingResearch.ts";
import { composeConsultingResearchViewModel, moveSection } from "../lib/composeConsultingResearchViewModel.ts";
import { buildReviewFixture } from "../fixtures/buildReviewFixture.ts";

export function ConsultingResearchWorkbench({ packet = buildReviewFixture() }: { packet?: unknown }) {
  const adapted = useMemo(() => adaptConsultingResearch(packet), [packet]);
  const [selected, setSelected] = useState<SectionId | null>(null);
  const view = useMemo(
    () => composeConsultingResearchViewModel({
      isLoading: false,
      review: adapted.review,
      rejected: adapted.rejected,
      selectedSectionId: selected,
    }),
    [adapted, selected],
  );
  const onKey = (key: string) => {
    setSelected(moveSection(view.review.sections.map((section) => section.section_id), view.selectedSectionId, key));
  };
  return (
    <section aria-labelledby="consulting-research-heading" className="min-w-0 space-y-4 p-4 text-zinc-100">
      <a href="#consulting-research-sections" className="sr-only focus:not-sr-only focus:rounded focus:bg-zinc-900 focus:px-3 focus:py-2">
        Skip to research sections
      </a>
      <header>
        <p className="text-xs uppercase tracking-wide text-zinc-400">Research review</p>
        <h1 id="consulting-research-heading" className="text-xl font-semibold">{view.review.display_name}</h1>
        <p className="text-sm text-zinc-300">{view.review.engagement_id} · {view.review.offering_kind}</p>
      </header>
      <div role="status" aria-live="polite" className="rounded border border-zinc-700 p-3 text-sm">
        {view.surface.toUpperCase()} {view.statusMessage}
      </div>
      <p className="text-sm"><span className="text-zinc-400">Question.</span> {view.review.research_question}</p>
      <p className="text-sm"><span className="text-zinc-400">Scope.</span> {view.review.scope}</p>
      <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable research sections">
        <table id="consulting-research-sections" className="min-w-full text-left text-sm">
          <thead>
            <tr>
              <th scope="col">Section</th>
              <th scope="col">Class</th>
              <th scope="col">Freshness</th>
              <th scope="col">Missing</th>
            </tr>
          </thead>
          <tbody>
            {view.review.sections.map((section) => {
              const active = section.section_id === view.selectedSectionId;
              return (
                <tr key={section.section_id}>
                  <th scope="row">
                    <button
                      type="button"
                      aria-pressed={active}
                      className="motion-reduce:transition-none rounded px-2 py-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
                      onClick={() => setSelected(section.section_id)}
                      onKeyDown={(event) => {
                        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
                          event.preventDefault();
                          onKey(event.key);
                        }
                      }}
                    >
                      {section.section_id}
                    </button>
                  </th>
                  <td>{section.items.map((item) => item.evidence_class).join(", ") || "unavailable"}</td>
                  <td>{section.items.some((item) => item.fresh === false) ? "stale" : "not dated"}</td>
                  <td>{section.missing.join(", ") || "none listed"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <section aria-label="Confidence and limitations">
        <p>Confidence: {view.review.confidence_label ?? "unavailable"}</p>
        <ul>{view.review.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        <p>Blockers: {view.review.blockers.join("; ") || "none listed"}</p>
        <p>Next action (display only): {view.review.next_action}</p>
      </section>
      <section aria-label="Validation timeline">
        <ol>
          {view.review.timeline.map((event) => (
            <li key={event.event_id}>{event.label} · {event.at ?? "date unavailable"} · {event.evidence_class}</li>
          ))}
        </ol>
      </section>
      <pre tabIndex={0} className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-zinc-950 p-3 text-xs">
        {JSON.stringify(view.exportPreview?.payload ?? { accepted: false, reason: view.exportPreview?.reason }, null, 2)}
      </pre>
    </section>
  );
}
