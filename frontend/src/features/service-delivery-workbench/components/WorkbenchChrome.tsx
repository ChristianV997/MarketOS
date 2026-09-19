import {
  LIFECYCLE_STATES,
  PRIORITY_SERVICE_IDS,
  PRIORITY_SERVICE_LABELS,
  type LifecycleState,
  type SurfaceState,
} from "../contracts/serviceEngagementProjection.ts";
import { EVIDENCE_CLASSES } from "../contracts/serviceEngagementProjection.ts";
import { EMPTY_FILTERS, type WorkbenchFilters } from "../lib/filterEngagements.ts";

const SURFACE_STYLES: Record<SurfaceState, string> = {
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  partial: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  stale: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  blocked: "border-orange-500/40 bg-orange-500/10 text-orange-200",
  empty: "border-zinc-600/40 bg-zinc-800/40 text-zinc-300",
  unavailable: "border-zinc-500/40 bg-zinc-800/50 text-zinc-400",
  loading: "border-indigo-500/30 bg-indigo-500/10 text-indigo-200",
};

export function WorkbenchStatusBanner({
  surface,
  message,
}: {
  surface: SurfaceState;
  message: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`rounded-lg border px-3 py-2 text-sm ${SURFACE_STYLES[surface]}`}
    >
      <p>
        <span className="font-medium uppercase tracking-wide text-[11px]">{surface}</span>
        <span className="ml-2">{message}</span>
      </p>
      <p className="mt-1 text-[11px]">
        Read-only operator workbench. No client accounts, messages, publishing, campaign edits, or charges.
      </p>
    </div>
  );
}

export function FilterBar({
  filters,
  onChange,
  count,
}: {
  filters: WorkbenchFilters;
  onChange: (next: WorkbenchFilters) => void;
  count: number;
}) {
  return (
    <form
      className="grid gap-3 rounded-lg border border-white/[0.06] bg-[#111113] p-3 md:grid-cols-4"
      onSubmit={(event) => event.preventDefault()}
      aria-label="Filter engagements without changing source order"
    >
      <label className="block text-[11px] uppercase tracking-widest text-zinc-400">
        Search
        <input
          className="mt-1 w-full rounded-md border border-white/[0.08] bg-[#0a0a0b] px-2.5 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          value={filters.query}
          onChange={(event) => onChange({ ...filters, query: event.target.value })}
          placeholder="Client, engagement, service"
        />
      </label>
      <label className="block text-[11px] uppercase tracking-widest text-zinc-400">
        Service
        <select
          className="mt-1 w-full rounded-md border border-white/[0.08] bg-[#0a0a0b] px-2.5 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          value={filters.serviceId}
          onChange={(event) => onChange({
            ...filters,
            serviceId: event.target.value as WorkbenchFilters["serviceId"],
          })}
        >
          <option value="all">All priority services</option>
          {PRIORITY_SERVICE_IDS.map((id) => (
            <option key={id} value={id}>{PRIORITY_SERVICE_LABELS[id]}</option>
          ))}
        </select>
      </label>
      <label className="block text-[11px] uppercase tracking-widest text-zinc-400">
        Lifecycle
        <select
          className="mt-1 w-full rounded-md border border-white/[0.08] bg-[#0a0a0b] px-2.5 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          value={filters.lifecycle}
          onChange={(event) => onChange({
            ...filters,
            lifecycle: event.target.value as WorkbenchFilters["lifecycle"],
          })}
        >
          <option value="all">All states</option>
          {LIFECYCLE_STATES.map((state) => (
            <option key={state} value={state}>{state}</option>
          ))}
        </select>
      </label>
      <label className="block text-[11px] uppercase tracking-widest text-zinc-400">
        Evidence class
        <select
          className="mt-1 w-full rounded-md border border-white/[0.08] bg-[#0a0a0b] px-2.5 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          value={filters.evidenceClass}
          onChange={(event) => onChange({
            ...filters,
            evidenceClass: event.target.value as WorkbenchFilters["evidenceClass"],
          })}
        >
          <option value="all">Any class</option>
          {EVIDENCE_CLASSES.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
      </label>
      <div className="md:col-span-4 flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-400">
        <p>{count} visible · source order unchanged</p>
        <button
          type="button"
          className="rounded-md border border-white/[0.08] px-2 py-1 text-zinc-200 hover:bg-white/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          onClick={() => onChange(EMPTY_FILTERS)}
        >
          Clear filters
        </button>
      </div>
    </form>
  );
}

export function lifecycleLabel(state: LifecycleState): string {
  return state.replace(/_/g, " ");
}
