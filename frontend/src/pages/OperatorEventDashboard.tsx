import { useMemo, useState } from "react";
import type { EventQueryParams, EventSource } from "@/lib/canonicalEventsApi";
import { useCommerceRuns, useEventTimeline, useEventsReadiness, useShopifyImports } from "@/hooks/useCanonicalEvents";

type Tab = "timeline" | "commerce" | "shopify";
const badge = "inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium";

function EmptyState({ message }: { message: string }) {
  return <div className="rounded-lg border border-dashed border-zinc-700 bg-zinc-900/40 p-6 text-sm text-zinc-400">
    <p>{message}</p>
    <ol className="mt-3 list-decimal space-y-1 pl-5 text-xs text-zinc-500">
      <li>Generate events with <code>scripts/run_commerce_mvp_slice.py --write-jsonl …</code>.</li>
      <li>Set <code>MARKETOS_EVENT_READ_JSONL_PATH</code> server-side for JSONL API reads.</li>
      <li>Configure Supabase staging server-side only when selecting that source.</li>
    </ol>
  </div>;
}

function Warnings({ values }: { values?: string[] }) {
  return values?.length ? <div className="mt-3 rounded border border-amber-500/20 bg-amber-500/5 p-2 text-xs text-amber-200">{values.join(" · ")}</div> : null;
}

function SafetyBadges() {
  const values = [
    ["Read-only", "border-sky-500/30 bg-sky-500/10 text-sky-300"],
    ["Advisory", "border-violet-500/30 bg-violet-500/10 text-violet-300"],
    ["No mutations", "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"],
    ["No credentials in browser", "border-amber-500/30 bg-amber-500/10 text-amber-300"],
  ];
  return <div className="flex flex-wrap gap-2">{values.map(([label, style]) => <span key={label} className={`${badge} ${style}`}>{label}</span>)}</div>;
}

export default function OperatorEventDashboard() {
  const [draft, setDraft] = useState<EventQueryParams>({ source: "jsonl", limit: 50 });
  const [params, setParams] = useState<EventQueryParams>(draft);
  const [tab, setTab] = useState<Tab>("timeline");
  const timeline = useEventTimeline(params);
  const commerce = useCommerceRuns(params);
  const shopify = useShopifyImports(params);
  const readiness = useEventsReadiness();
  const loading = timeline.isLoading || commerce.isLoading || shopify.isLoading || readiness.isLoading;
  const error = timeline.error || commerce.error || shopify.error || readiness.error;
  const eventTypes = useMemo(() => Object.entries(timeline.data?.event_type_counts ?? {}), [timeline.data]);
  const update = (key: keyof EventQueryParams, value: string | number) => setDraft((current) => ({ ...current, [key]: value || undefined }));
  const refresh = () => {
    setParams({ ...draft, offset: 0 });
    void Promise.all([timeline.refetch(), commerce.refetch(), shopify.refetch(), readiness.refetch()]);
  };

  return <div className="mx-auto max-w-7xl space-y-5 p-6">
    <header className="space-y-3">
      <div><h1 className="text-xl font-semibold text-zinc-100">Operator Event Dashboard</h1><p className="mt-1 text-sm text-zinc-500">Read-only canonical events, Commerce MVP runs, and Shopify import summaries.</p></div>
      <SafetyBadges />
    </header>

    <section className="grid gap-3 md:grid-cols-3">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4"><p className="text-xs text-zinc-500">JSONL event source</p><p className="mt-1 text-sm text-zinc-200">{readiness.data?.jsonl_path_configured ? "Configured server-side" : "Not configured"}</p></div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4"><p className="text-xs text-zinc-500">Supabase staging reader</p><p className="mt-1 text-sm text-zinc-200">{readiness.data?.supabase_staging?.configured ? "Configured server-side" : "Not configured"}</p><p className="mt-1 text-[11px] text-zinc-500">Server-side only; no browser credentials.</p></div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4"><p className="text-xs text-zinc-500">No-write guarantee</p><p className="mt-1 text-sm text-emerald-300">{readiness.data?.read_only ? "Enabled" : "Unavailable"}</p><p className="mt-1 text-[11px] text-zinc-500">Selected source: {params.source ?? "jsonl"}</p></div>
    </section>

    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <label className="text-xs text-zinc-500">Source<select aria-label="Event source" value={draft.source ?? "jsonl"} onChange={(event) => update("source", event.target.value as EventSource)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200"><option value="jsonl">JSONL</option><option value="supabase_staging">Supabase staging</option></select></label>
        <label className="text-xs text-zinc-500">Workspace<input value={draft.workspace_id ?? ""} onChange={(event) => update("workspace_id", event.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200" placeholder="optional" /></label>
        <label className="text-xs text-zinc-500">Event type<input value={draft.event_type ?? ""} onChange={(event) => update("event_type", event.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200" placeholder="optional" /></label>
        <label className="text-xs text-zinc-500">Aggregate type<input value={draft.aggregate_type ?? ""} onChange={(event) => update("aggregate_type", event.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200" placeholder="optional" /></label>
        <label className="text-xs text-zinc-500">Limit<select aria-label="Event limit" value={draft.limit ?? 50} onChange={(event) => update("limit", Number(event.target.value))} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200">{[25, 50, 100, 250].map((value) => <option key={value}>{value}</option>)}</select></label>
        <button type="button" onClick={refresh} className="mt-5 h-9 rounded bg-indigo-500 px-4 text-sm font-medium text-white hover:bg-indigo-400">Refresh read view</button>
      </div>
    </section>

    {loading && <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6 text-sm text-zinc-400">Loading read-only event data…</div>}
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error.message} Check the configured server-side event source and try again.</div>}
    {!loading && !error && <>
      <div className="flex gap-2 border-b border-zinc-800">{(["timeline", "commerce", "shopify"] as Tab[]).map((item) => <button key={item} type="button" onClick={() => setTab(item)} className={`px-3 py-2 text-sm ${tab === item ? "border-b-2 border-indigo-400 text-indigo-300" : "text-zinc-500 hover:text-zinc-200"}`}>{item === "commerce" ? "Commerce MVP" : item === "shopify" ? "Shopify imports" : "Timeline"}</button>)}</div>
      {tab === "timeline" && <section className="space-y-3"><div className="flex flex-wrap gap-2 text-xs text-zinc-400"><span>{timeline.data?.events.length ?? 0} events</span>{eventTypes.map(([type, count]) => <span key={type} className="rounded bg-zinc-800 px-2 py-1">{type}: {count}</span>)}</div><Warnings values={timeline.data?.warnings} />{timeline.data?.events.length ? <div className="overflow-x-auto rounded-lg border border-zinc-800"><table className="min-w-full text-left text-xs"><thead className="bg-zinc-900 text-zinc-500"><tr>{["Occurred", "Event", "Aggregate", "Source", "Replay hash", "Safety"].map((heading) => <th key={heading} className="px-3 py-2 font-medium">{heading}</th>)}</tr></thead><tbody>{timeline.data.events.map((event) => <tr key={event.event_id} className="border-t border-zinc-800 text-zinc-300"><td className="whitespace-nowrap px-3 py-3">{new Date(event.occurred_at * 1000).toLocaleString()}</td><td className="px-3 py-3 font-mono">{event.event_type}</td><td className="px-3 py-3">{event.aggregate_type}<br /><span className="text-zinc-500">{event.aggregate_id}</span></td><td className="px-3 py-3">{event.source}</td><td className="px-3 py-3 font-mono text-zinc-500">{event.replay_hash.slice(0, 12)}</td><td className="px-3 py-3"><div className="flex flex-wrap gap-1">{event.dry_run && <span className={`${badge} border-sky-500/30 text-sky-300`}>dry run</span>}{event.advisory && <span className={`${badge} border-violet-500/30 text-violet-300`}>advisory</span>}{event.read_only && <span className={`${badge} border-emerald-500/30 text-emerald-300`}>read-only</span>}{event.pii_redacted && <span className={`${badge} border-amber-500/30 text-amber-300`}>PII redacted</span>}</div>{event.authority_flags.length > 0 && <p className="mt-1 max-w-48 truncate text-[10px] text-zinc-500" title={event.authority_flags.join(", ")}>{event.authority_flags.join(", ")}</p>}</td></tr>)}</tbody></table></div> : <EmptyState message="No canonical events matched the current filters." />}</section>}
      {tab === "commerce" && <section className="space-y-3">{commerce.data?.runs.length ? commerce.data.runs.map((run) => <article key={run.run_id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-medium text-zinc-100">{run.query || "Commerce MVP run"}</h2><p className="mt-1 text-xs text-zinc-500">{run.run_id} · {run.event_count} events · {run.candidate_count} candidates</p></div><span className={`${badge} border-indigo-500/30 text-indigo-300`}>{run.status}</span></div><p className="mt-3 text-sm text-zinc-300">Selected candidate: {run.selected_candidate ?? "not recorded"}</p><div className="mt-3 flex flex-wrap gap-2 text-xs text-zinc-400">{[{ label: "Economics", present: run.economics_present }, { label: "Creative", present: run.creative_packet_present }, { label: "Landing page", present: run.landing_page_packet_present }, { label: "Store draft", present: run.store_draft_packet_present }, { label: "Approval", present: run.approval_packet_present }].map((item) => <span key={item.label} className="rounded bg-zinc-800 px-2 py-1">{item.label}: {item.present ? "present" : "missing"}</span>)}</div><Warnings values={[...run.warnings, ...run.blockers]} /></article>) : <EmptyState message="No Commerce MVP run summaries are available for this source." />}</section>}
      {tab === "shopify" && <section className="space-y-3">{shopify.data?.imports.length ? shopify.data.imports.map((item) => <article key={item.batch_id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-medium text-zinc-100">Shopify import {item.batch_id}</h2><p className="mt-1 text-xs text-zinc-500">{item.event_count} advisory events · workspace {item.workspace_id ?? "unknown"}</p></div><span className={`${badge} border-emerald-500/30 text-emerald-300`}>{item.pii_redacted ? "PII redacted" : "No PII flag"}</span></div><div className="mt-3 grid grid-cols-2 gap-2 text-sm text-zinc-300 md:grid-cols-4"><span>Products: {item.product_count}</span><span>Orders: {item.order_count}</span><span>Customers: {item.customer_count}</span><span>AOV: {item.average_order_value.toFixed(2)}</span></div><p className="mt-3 text-xs text-zinc-500">Observed revenue: {item.observed_revenue_total.toFixed(2)}. This is read-only historical context, not a forecast.</p><Warnings values={item.warnings} /></article>) : <EmptyState message="No Shopify read-only import summaries are available for this source." />}</section>}
    </>}
  </div>;
}
