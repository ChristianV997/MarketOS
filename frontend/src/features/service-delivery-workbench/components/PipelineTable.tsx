import { PRIORITY_SERVICE_LABELS, type ServiceEngagement } from "../contracts/serviceEngagementProjection.ts";
import { lifecycleLabel } from "./WorkbenchChrome.tsx";

export function PipelineTable({
  rows,
  selectedId,
  onSelect,
  onMove,
  emptyCopy,
}: {
  rows: ServiceEngagement[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onMove: (delta: number) => void;
  emptyCopy: string;
}) {
  return (
    <section aria-labelledby="pipeline-heading" className="overflow-hidden rounded-lg border border-white/[0.06]">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2">
        <h2 id="pipeline-heading" tabIndex={-1} className="text-sm font-semibold text-zinc-100 outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">Service pipeline</h2>
        <p className="text-[11px] text-zinc-400">Arrow keys move selection</p>
      </div>
      {rows.length === 0 ? (
        <p className="p-4 text-sm text-zinc-400">{emptyCopy}</p>
      ) : (
        <div
          className="overflow-x-auto"
          tabIndex={0}
          role="region"
          aria-label="Scrollable service pipeline table"
        >
          <table className="min-w-full text-left text-sm">
            <caption className="sr-only">Server-ordered service engagements. Filtering does not re-rank.</caption>
            <thead className="bg-[#111113] text-[11px] uppercase tracking-widest text-zinc-400">
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
                    className={`border-t border-white/[0.04] ${
                      selected ? "bg-indigo-500/10" : "hover:bg-white/[0.03]"
                    }`}
                  >
                    <th scope="row" className="px-3 py-2 font-medium text-zinc-100">
                      <button
                        type="button"
                        tabIndex={selected ? 0 : -1}
                        aria-pressed={selected}
                        aria-current={selected ? "true" : undefined}
                        className="block w-full rounded text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
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
                          }
                        }}
                      >
                        {row.intake.display_name}
                        <span className="block text-[11px] font-normal text-zinc-400">{row.engagement_id}</span>
                      </button>
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
