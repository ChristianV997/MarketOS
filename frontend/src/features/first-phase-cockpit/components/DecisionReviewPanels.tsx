import type { RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket";

export function DecisionTimelinePanel({ candidate }: { candidate: RankedCandidateRow }) {
  return (
    <section aria-labelledby="decision-timeline-heading" className="mt-4">
      <h4 id="decision-timeline-heading" className="text-xs font-medium text-zinc-300">
        Evidence decision timeline
      </h4>
      <p className="mt-1 text-[11px] text-zinc-500">
        Transitions are shown only when the projection supplied them. Missing steps stay unavailable.
      </p>
      <ol className="mt-2 space-y-2" aria-label="Candidate evidence timeline">
        {candidate.decisionTimeline.map((event) => (
          <li
            key={event.kind}
            className={`rounded border p-2 text-xs ${
              event.status === "unavailable"
                ? "border-zinc-800 bg-zinc-950/40 text-zinc-500"
                : "border-zinc-700 bg-zinc-900/60 text-zinc-200"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{event.kind.replace(/_/g, " ")}</span>
              <span className="text-[10px] uppercase tracking-wide">{event.status}</span>
            </div>
            <p className="mt-1">{event.summary.replace(/_/g, " ")}</p>
          </li>
        ))}
      </ol>
      <h5 className="mt-3 text-[11px] uppercase tracking-wide text-zinc-500">Promotion transitions</h5>
      <ul className="mt-1 space-y-1 text-xs text-zinc-300">
        {candidate.promotionTransitions.map((item, index) => (
          <li key={`${item.from}-${item.to}-${index}`}>
            {item.status === "unavailable"
              ? "unavailable"
              : `${item.from ?? "unspecified"} → ${item.to ?? "unspecified"}${item.reason ? ` (${item.reason.replace(/_/g, " ")})` : ""}`}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function NextActionWorkflowPanel({ candidate }: { candidate: RankedCandidateRow }) {
  const workflow = candidate.nextActionWorkflow;
  return (
    <section aria-labelledby="next-action-heading" className="mt-4 rounded border border-zinc-800 bg-zinc-950/40 p-3">
      <h4 id="next-action-heading" className="text-xs font-medium text-zinc-300">Human next-action workflow</h4>
      <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-zinc-500">Next action</dt>
          <dd className="text-zinc-100">{workflow.action.replace(/_/g, " ")}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Responsible party</dt>
          <dd>{workflow.responsibleParty}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Expected evidence type</dt>
          <dd>{workflow.expectedEvidenceType.replace(/_/g, " ")}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Human confirmation required</dt>
          <dd>{workflow.humanConfirmationRequired ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Allowed in read-only cockpit</dt>
          <dd>{workflow.allowedInReadOnlyCockpit ? "review only" : "not executable"}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Future action</dt>
          <dd>{workflow.futureActionStatus} — {workflow.futureActionNote}</dd>
        </div>
      </dl>
      <p className="mt-2 text-[11px] text-zinc-500">
        Missing evidence: {workflow.missingEvidence.length ? workflow.missingEvidence.join(" · ").replace(/_/g, " ") : "none listed"}
      </p>
      <p className="sr-only">
        No cockpit control can send messages, place orders, publish ads, change prices, approve suppliers, or issue refunds.
      </p>
    </section>
  );
}

export function CommercialReviewTags({ candidate }: { candidate: RankedCandidateRow }) {
  return (
    <ul className="mt-2 flex flex-wrap gap-1" aria-label="Commercial review tags">
      {candidate.commercialReviewTags.map((tag) => (
        <li
          key={tag}
          className={`rounded border px-1.5 py-0.5 text-[10px] ${
            tag === "live_validated"
              ? "border-lime-500/30 text-lime-200"
              : tag === "fixture" || tag === "manual_import" || tag === "simulated"
                ? "border-amber-500/30 text-amber-200"
                : tag === "reject" || tag === "blocked" || tag.includes("launch")
                  ? "border-rose-500/30 text-rose-200"
                  : "border-zinc-600 text-zinc-300"
          }`}
        >
          {tag.replace(/_/g, " ")}
        </li>
      ))}
    </ul>
  );
}
