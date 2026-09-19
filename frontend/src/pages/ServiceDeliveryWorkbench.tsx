import { useEffect, useRef } from "react";
import { PipelineTable } from "../features/service-delivery-workbench/components/PipelineTable";
import { EngagementWorkflow } from "../features/service-delivery-workbench/components/EngagementWorkflow";
import { FilterBar, WorkbenchStatusBanner } from "../features/service-delivery-workbench/components/WorkbenchChrome";
import { useServiceDeliveryWorkbench } from "../features/service-delivery-workbench/hooks/useServiceDeliveryWorkbench";
import { moveSelection } from "../features/service-delivery-workbench/lib/composeWorkbenchViewModel";

export default function ServiceDeliveryWorkbench() {
  const { view, filters, setFilters, setSelectedId, recovery } = useServiceDeliveryWorkbench();
  const tableRef = useRef<HTMLDivElement>(null);
  const skipInitialFocus = useRef(true);

  useEffect(() => {
    if (skipInitialFocus.current) {
      skipInitialFocus.current = false;
      return;
    }
    const selected = tableRef.current?.querySelector<HTMLElement>("[aria-selected='true']");
    selected?.focus();
  }, [view.selected?.engagement_id]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 overflow-x-hidden p-3 md:p-5">
      <a
        href="#pipeline-heading"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-zinc-900 focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to service pipeline
      </a>
      <header className="space-y-2">
        <h1 className="text-xl font-semibold text-zinc-50">Service delivery workbench</h1>
        <p className="text-sm text-zinc-400">
          Operator review for Product Validation Sprint, Unit Economics + CAC/ROAS Diagnostic,
          Launch Draft Pack, and Managed Acquisition and CRO. Read-only: the canonical GET is
          {view.liveEndpointUnavailable ? " unavailable" : " available read-only"}
          ; fixture/manual/simulated rows are not live client evidence; draft-ready is not commercially validated; economics are backend display copies only.
        </p>
      </header>

      <WorkbenchStatusBanner surface={view.surface} message={view.statusMessage} />

      <FilterBar filters={filters} onChange={setFilters} count={view.filtered.length} />

      <div ref={tableRef}>
        <PipelineTable
          rows={view.filtered}
          selectedId={view.selected?.engagement_id ?? null}
          onSelect={setSelectedId}
          onMove={(delta) => {
            const next = moveSelection(view.filtered, view.selected?.engagement_id ?? null, delta);
            if (next) setSelectedId(next);
          }}
        />
      </div>

      {view.selected ? (
        <EngagementWorkflow engagement={view.selected} exportPreview={view.exportPreview} />
      ) : (
        <section className="rounded-lg border border-dashed border-white/[0.08] p-6 text-sm text-zinc-400">
          <p>Nothing selected.</p>
          <p className="mt-2 text-xs">{recovery}</p>
        </section>
      )}
    </div>
  );
}
