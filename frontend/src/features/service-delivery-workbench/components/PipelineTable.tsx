import {
  PRIORITY_SERVICE_LABELS,
  type EvidenceClass,
  type ServiceEngagement,
} from "../contracts/serviceEngagementProjection.ts";
import { lifecycleLabel } from "./WorkbenchChrome.tsx";

function evidenceClassLabel(value: EvidenceClass): string {
  return value.replace(/_/g, " ");
}

function ownerLabel(owner: ServiceEngagement["operator_review_cues"]["nba_owner"]): string {
  if (owner === "client") return "Client";
  if (owner === "blocked") return "Blocked";
  return "Operator";
}

function economicsCue(cues: ServiceEngagement["operator_review_cues"]): string {
  const fee = evidenceClassLabel(cues.fee_evidence_class);
  const contribution = evidenceClassLabel(cues.contribution_evidence_class);
  if (!cues.economics_display_only) {
    return `Fee ${fee} · Contrib ${contribution}`;
  }
  return `Display only · fee ${fee}`;
}

export function PipelineTable({
  rows,
  selectedId,
  onSelect,
  onMove,
}: {
  rows: ServiceEngagement[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onMove: (delta: number) => void;
}) {
  return (
    <section aria-labelledby="pipeline-heading" className="overflow-hidden rounded-lg border border-white/[0.06]">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2">
        <h2 id="pipeline-heading" className="text-sm font-semibold text-zinc-100">Service pipeline</h2>
        <p className="text-[11px] text-zinc-500">Arrow keys move selection · scan cues are not authority</p>
      </div>
      {rows.length === 0 ? (
        <p className="p-4 text-sm text-zinc-400">No engagements match. Clear filters to recover the source list.</p>
      ) : (
        <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable service pipeline">
          <table className="min-w-[56rem] w-full text-left text-sm" role="table">
            <caption className="sr-only">
              Server-ordered service engagements with evidence, economics display, and next-action owner cues.
              Filtering does not re-rank. Cues are planning copies only and never authorize execution.
            </caption>
            <thead className="bg-[#111113] text-[11px] uppercase tracking-widest text-zinc-500">
              <tr>
                <th scope="col" className="px-3 py-2">Client</th>
                <th scope="col" className="px-3 py-2">Service</th>
                <th scope="col" className="px-3 py-2">Lifecycle</th>
                <th scope="col" className="px-3 py-2">Evidence</th>
                <th scope="col" className="px-3 py-2">Economics</th>
                <th scope="col" className="px-3 py-2">Owner</th>
                <th scope="col" className="px-3 py-2">Next action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const selected = row.engagement_id === selectedId;
                const cues = row.operator_review_cues;
                return (
                  <tr
                    key={row.engagement_id}
                    tabIndex={selected ? 0 : -1}
                    aria-selected={selected}
                    className={`cursor-pointer border-t border-white/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-indigo-400 ${
                      selected ? "bg-indigo-500/10" : "hover:bg-white/[0.03]"
                    }`}
                    onClick={() => onSelect(row.engagement_id)}
                    onKeyDown={(event) => {
                      if (event.key === "ArrowDown") {
                        event.preventDefault();
                        onMove(1);
                      } else if (event.key === "ArrowUp") {
                        event.preventDefault();
                        onMove(-1);
                      } else if (event.key === "Home") {
                        event.preventDefault();
                        onMove(-rows.length);
                      } else if (event.key === "End") {
                        event.preventDefault();
                        onMove(rows.length);
                      } else if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelect(row.engagement_id);
                      }
                    }}
                  >
                    <th scope="row" className="px-3 py-2 font-medium text-zinc-100">
                      {row.intake.display_name}
                      <div className="text-[11px] font-normal text-zinc-500">{row.engagement_id}</div>
                    </th>
                    <td className="px-3 py-2 text-zinc-300">{PRIORITY_SERVICE_LABELS[row.service_id]}</td>
                    <td className="px-3 py-2">
                      <span className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[11px] text-zinc-200">
                        {lifecycleLabel(row.lifecycle_state)}
                      </span>
                      {cues.data_inadequate ? (
                        <div className="mt-1 text-[11px] text-orange-300">Data inadequate</div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-zinc-300">
                      <div>
                        {cues.evidence_count} · {evidenceClassLabel(cues.strongest_evidence_class)}
                      </div>
                      <div className="text-[11px] text-zinc-500">
                        {cues.evidence_not_live_validated
                          ? "Not live validated"
                          : "Class label only · not commercial proof"}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-zinc-300">
                      <div>{economicsCue(cues)}</div>
                      <div className="text-[11px] text-zinc-500">
                        {cues.financial_ready ? "Financial copy ready" : "Financial copy incomplete"}
                        {" · "}frontend does not calculate
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[11px] text-zinc-200">
                        {ownerLabel(cues.nba_owner)}
                      </span>
                      <div className="mt-1 text-[11px] text-zinc-500">No live execution</div>
                    </td>
                    <td className="px-3 py-2 text-zinc-400">
                      {cues.nba_action_short || row.next_best_action.action}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
