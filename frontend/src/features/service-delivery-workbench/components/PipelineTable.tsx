import { PRIORITY_SERVICE_LABELS, type ServiceEngagement } from "../contracts/serviceEngagementProjection.ts";
import { lifecycleLabel } from "./WorkbenchChrome.tsx";

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
        <p className="text-[11px] text-zinc-500">Arrow keys move selection</p>
      </div>
      {rows.length === 0 ? (
        <p className="p-4 text-sm text-zinc-400">No engagements match. Clear filters to recover the source list.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-[#111113] text-[11px] uppercase tracking-widest text-zinc-500">
              <tr>
                <th scope="col" className="px-3 py-2">Client</th>
                <th scope="col" className="px-3 py-2">Service</th>
                <th scope="col" className="px-3 py-2">Lifecycle</th>
                <th scope="col" className="px-3 py-2">Next action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const selected = row.engagement_id === selectedId;
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
                    </td>
                    <td className="px-3 py-2 text-zinc-400">{row.next_best_action.action}</td>
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
