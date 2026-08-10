import { useEffect, useMemo, useState } from "react";
import type { CompetitionSummaryView, EventQueryParams, EventSource, OpportunityScoreView } from "@/lib/canonicalEventsApi";
import { useCommerceRuns, useCompetitionSummaries, useEventTimeline, useEventsReadiness, useOpportunityRankings, usePublicCommerceMvpRun, useShopifyImports } from "@/hooks/useCanonicalEvents";
import { trackSafeEvent } from "@/lib/analytics";

type Tab = "timeline" | "commerce" | "shopify" | "opportunity" | "competition";
const badge = "inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium";
const provenanceStyle: Record<string, string> = {
  observed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  derived: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  assumed: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  unavailable: "border-zinc-600/30 bg-zinc-700/20 text-zinc-500",
};

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

function OpportunityScoreCard({ score, isTop }: { score: OpportunityScoreView; isTop: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return <article className={`rounded-lg border p-4 ${isTop ? "border-indigo-500/40 bg-indigo-500/5" : "border-zinc-800 bg-zinc-900/40"}`}>
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><h3 className="font-medium text-zinc-100">{score.product_name}{isTop && <span className={`${badge} ml-2 border-indigo-500/30 text-indigo-300`}>Recommended candidate</span>}</h3><p className="mt-1 text-xs text-zinc-500">{score.candidate_id}</p></div>
      <div className="text-right"><p className="text-lg font-semibold text-zinc-100">{score.composite_score.toFixed(1)}</p><p className="text-[11px] text-zinc-500">composite score</p></div>
    </div>
    <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-zinc-300 md:grid-cols-5">
      <span>Confidence: {(score.confidence * 100).toFixed(0)}%</span>
      <span className="text-emerald-300">Observed: {score.observed_pct.toFixed(0)}%</span>
      <span className="text-sky-300">Derived: {score.derived_pct.toFixed(0)}%</span>
      <span className="text-amber-300">Assumed: {score.assumed_pct.toFixed(0)}%</span>
      <span className="text-zinc-500">Unknown: {score.unknown_pct.toFixed(0)}%</span>
    </div>
    <p className="mt-3 text-xs text-zinc-400">Recommended action: <span className="font-medium text-zinc-200">{score.recommended_action.replace(/_/g, " ")}</span></p>
    {score.reasons.length > 0 && <div className="mt-2 text-xs text-zinc-400"><p className="text-zinc-500">Why it ranked here:</p><ul className="mt-1 list-disc space-y-0.5 pl-4">{score.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}
    {score.risks.length > 0 && <div className="mt-2 text-xs text-red-300"><p className="text-red-400/80">Risks:</p><ul className="mt-1 list-disc space-y-0.5 pl-4">{score.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul></div>}
    {score.unknowns.length > 0 && <div className="mt-2 text-xs text-zinc-500"><p>Unknowns (reduce confidence, never fabricated):</p><ul className="mt-1 list-disc space-y-0.5 pl-4">{score.unknowns.map((unknown) => <li key={unknown}>{unknown}</li>)}</ul></div>}
    {score.blockers.length > 0 && <Warnings values={score.blockers} />}
    <button type="button" onClick={() => setExpanded((value) => !value)} className="mt-3 text-xs text-indigo-300 hover:text-indigo-200">{expanded ? "Hide" : "Show"} score breakdown ({score.dimensions.length} dimensions)</button>
    {expanded && <div className="mt-2 overflow-x-auto rounded border border-zinc-800"><table className="min-w-full text-left text-xs"><thead className="bg-zinc-900 text-zinc-500"><tr>{["Dimension", "Raw", "Normalized", "Weight", "Contribution", "Provenance", "Reason"].map((heading) => <th key={heading} className="px-2 py-1.5 font-medium">{heading}</th>)}</tr></thead><tbody>{score.dimensions.map((dimension) => <tr key={dimension.name} className="border-t border-zinc-800 text-zinc-300"><td className="px-2 py-1.5 font-mono">{dimension.name}</td><td className="px-2 py-1.5">{dimension.raw_value ?? "—"}</td><td className="px-2 py-1.5">{dimension.normalized_value ?? "—"}</td><td className="px-2 py-1.5">{dimension.weight}</td><td className="px-2 py-1.5">{dimension.contribution}</td><td className="px-2 py-1.5"><span className={`${badge} ${provenanceStyle[dimension.provenance]}`}>{dimension.provenance}</span></td><td className="px-2 py-1.5 max-w-64 text-zinc-500">{dimension.reason}</td></tr>)}</tbody></table></div>}
  </article>;
}

function CompetitionSummaryCard({ summary }: { summary: CompetitionSummaryView }) {
  const [showOffers, setShowOffers] = useState(false);
  const margin = summary.margin;
  return <article className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><h2 className="font-medium text-zinc-100">{summary.query || "Competition & pricing"}</h2><p className="mt-1 text-xs text-zinc-500">{summary.run_id} · {summary.observed_competitor_count} observed competitor(s) · {summary.market_maturity}</p></div>
      <span className={`${badge} border-indigo-500/30 text-indigo-300`}>Confidence {(summary.confidence * 100).toFixed(0)}%</span>
    </div>
    <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-zinc-300 md:grid-cols-4">
      <span>Median price: {summary.observed_median_price ?? "unobserved"}</span>
      <span>Market saturation: {summary.market_saturation !== null ? `${(summary.market_saturation * 100).toFixed(0)}%` : "unobserved"}</span>
      <span>Observed offers: {summary.offers.length}</span>
      <span>Events: {summary.event_count}</span>
    </div>
    {margin && <div className="mt-3 rounded border border-zinc-800 bg-zinc-950/40 p-3 text-xs text-zinc-300">
      <p className="font-medium text-zinc-200">Supplier vs market</p>
      <div className="mt-1 grid grid-cols-2 gap-2 md:grid-cols-4">
        <span>Gross margin: {margin.observed_gross_margin ?? "unobserved"}</span>
        <span>Margin range: {margin.observed_margin_low ?? "—"} to {margin.observed_margin_high ?? "—"}</span>
        <span>Supplier advantage: {margin.observed_supplier_advantage ?? "unobserved"}</span>
        <span>Margin confidence: {(margin.observed_margin_confidence * 100).toFixed(0)}%</span>
      </div>
      <Warnings values={margin.warnings} />
    </div>}
    <button type="button" onClick={() => setShowOffers((value) => !value)} className="mt-3 text-xs text-indigo-300 hover:text-indigo-200">{showOffers ? "Hide" : "Show"} observed price distribution ({summary.offers.length} listing(s))</button>
    {showOffers && (summary.offers.length ? <div className="mt-2 overflow-x-auto rounded border border-zinc-800"><table className="min-w-full text-left text-xs"><thead className="bg-zinc-900 text-zinc-500"><tr>{["Title", "Source", "Price", "Brand", "Seller", "Rating", "Reviews", "Confidence"].map((heading) => <th key={heading} className="px-2 py-1.5 font-medium">{heading}</th>)}</tr></thead><tbody>{summary.offers.map((offer) => <tr key={offer.external_listing_id} className="border-t border-zinc-800 text-zinc-300"><td className="px-2 py-1.5 max-w-48 truncate" title={offer.title}>{offer.title || "(no title observed)"}</td><td className="px-2 py-1.5">{offer.source}</td><td className="px-2 py-1.5">{offer.price ?? "—"} {offer.currency}</td><td className="px-2 py-1.5">{offer.brand || "—"}</td><td className="px-2 py-1.5">{offer.seller || "—"}</td><td className="px-2 py-1.5">{offer.rating ?? "—"}</td><td className="px-2 py-1.5">{offer.review_count ?? "—"}</td><td className="px-2 py-1.5">{(offer.confidence * 100).toFixed(0)}%</td></tr>)}</tbody></table></div> : <EmptyState message="No competitor listings were observed for this run." />)}
  </article>;
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
  const [publicQuery, setPublicQuery] = useState("");
  const [publicWorkspace, setPublicWorkspace] = useState("demo");
  const [publicLimit, setPublicLimit] = useState(10);
  const [publicTarget, setPublicTarget] = useState<"none" | "jsonl" | "supabase_staging" | "both">("none");
  const [acknowledged, setAcknowledged] = useState(false);
  const [useOpportunityRanking, setUseOpportunityRanking] = useState(false);
  const [attemptCompetitionEvidence, setAttemptCompetitionEvidence] = useState(false);
  const [competitorUrls, setCompetitorUrls] = useState("");
  const [publicResult, setPublicResult] = useState<{ status: string; event_count: number; blockers: string[]; warnings: string[]; opportunity_ranking_used?: boolean; competition_evidence_attempted?: boolean } | null>(null);
  const timeline = useEventTimeline(params);
  const commerce = useCommerceRuns(params);
  const shopify = useShopifyImports(params);
  const opportunity = useOpportunityRankings(params);
  const competition = useCompetitionSummaries(params);
  const readiness = useEventsReadiness();
  const publicRun = usePublicCommerceMvpRun();
  const loading = timeline.isLoading || commerce.isLoading || shopify.isLoading || opportunity.isLoading || competition.isLoading || readiness.isLoading;
  const error = timeline.error || commerce.error || shopify.error || opportunity.error || competition.error || readiness.error;
  const eventTypes = useMemo(() => Object.entries(timeline.data?.event_type_counts ?? {}), [timeline.data]);
  useEffect(() => { trackSafeEvent("operator_event_dashboard_viewed", { source: params.source ?? "jsonl", read_only: true, advisory: true }); }, []);
  const update = (key: keyof EventQueryParams, value: string | number) => {
    setDraft((current) => ({ ...current, [key]: value || undefined }));
    if (key === "source") trackSafeEvent("operator_event_source_changed", { source: value, read_only: true, advisory: true });
  };
  const refresh = () => {
    trackSafeEvent("operator_event_filters_applied", { source: draft.source ?? "jsonl", limit: draft.limit ?? 50, read_only: true, advisory: true });
    trackSafeEvent("operator_event_refresh_clicked", { source: draft.source ?? "jsonl", read_only: true, advisory: true });
    setParams({ ...draft, offset: 0 });
    void Promise.all([timeline.refetch(), commerce.refetch(), shopify.refetch(), opportunity.refetch(), competition.refetch(), readiness.refetch()]);
  };
  const runPublicTest = () => {
    const parsedCompetitorUrls = competitorUrls.split(",").map((value) => value.trim()).filter(Boolean).slice(0, 5);
    trackSafeEvent("public_commerce_run_started", { source: "google_news_rss", max_signals: publicLimit, max_candidates: 5, event_target: publicTarget, use_opportunity_ranking: useOpportunityRanking, attempt_competition_evidence: attemptCompetitionEvidence, query_length: publicQuery.trim().length, read_only: true, advisory: true });
    publicRun.mutate({ query: publicQuery.trim(), workspace_id: publicWorkspace.trim() || "demo", max_signals: publicLimit, max_candidates: 5, allow_public_network: true, include_shopify_fixture_context: false, source: "google_news_rss", event_target: publicTarget, use_opportunity_ranking: useOpportunityRanking, attempt_competition_evidence: attemptCompetitionEvidence, competitor_urls: parsedCompetitorUrls }, { onSuccess: (result) => {
      setPublicResult(result);
      const eventName = result.status === "succeeded" ? "public_commerce_run_succeeded" : result.status === "stale_cache" ? "public_commerce_run_stale_cache" : result.status === "degraded" ? "public_commerce_run_degraded" : "public_commerce_run_blocked";
      trackSafeEvent(eventName, { source: "google_news_rss", status: result.status, event_count: result.event_count, signal_count: result.signal_count, candidate_count: result.candidate_count, event_target: publicTarget, opportunity_ranking_used: result.opportunity_ranking_used ?? false, competition_evidence_attempted: result.competition_evidence_attempted ?? false, read_only: true, advisory: true });
    } });
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

    <section className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
      <div><h2 className="text-sm font-medium text-zinc-100">Run public Commerce MVP test</h2><p className="mt-1 text-xs text-amber-200">This performs one manually acknowledged public/no-auth Google News RSS GET only. It is advisory, has no spend or store authority, and never accepts credentials or source URLs.</p></div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <label className="text-xs text-zinc-500">Query<input value={publicQuery} onChange={(event) => setPublicQuery(event.target.value)} placeholder="portable espresso maker" className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200" /></label>
        <label className="text-xs text-zinc-500">Workspace<input value={publicWorkspace} onChange={(event) => setPublicWorkspace(event.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200" /></label>
        <label className="text-xs text-zinc-500">Max signals<select value={publicLimit} onChange={(event) => setPublicLimit(Number(event.target.value))} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200">{[5, 10, 15].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="text-xs text-zinc-500">Event target<select value={publicTarget} onChange={(event) => setPublicTarget(event.target.value as typeof publicTarget)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200"><option value="none">No write</option><option value="jsonl">JSONL</option><option value="supabase_staging">Supabase staging</option><option value="both">Both</option></select></label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-zinc-400"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />I understand this performs a public no-auth Google News RSS GET only.</label>
        <label className="flex items-center gap-2 text-xs text-zinc-400"><input type="checkbox" checked={useOpportunityRanking} onChange={(event) => setUseOpportunityRanking(event.target.checked)} />Rank candidates with opportunity scoring instead of picking by source score alone.</label>
        <label className="flex items-center gap-2 text-xs text-zinc-400"><input type="checkbox" checked={attemptCompetitionEvidence} onChange={(event) => setAttemptCompetitionEvidence(event.target.checked)} />Gather public competitor pricing (requires opportunity ranking + server opt-in).</label>
        <button type="button" disabled={!acknowledged || !publicQuery.trim() || publicRun.isPending} onClick={runPublicTest} className="rounded bg-amber-500 px-4 py-2 text-sm font-medium text-zinc-950 disabled:cursor-not-allowed disabled:opacity-40">{publicRun.isPending ? "Running…" : "Run public test"}</button>
      </div>
      {attemptCompetitionEvidence && <label className="mt-3 block text-xs text-zinc-500">Competitor listing URLs (comma-separated, up to 5)<input value={competitorUrls} onChange={(event) => setCompetitorUrls(event.target.value)} placeholder="https://example.com/product/a, https://example.com/product/b" className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200" /></label>}
      {publicRun.error && <p className="mt-3 text-xs text-red-300">{publicRun.error.message}</p>}
      {publicResult && <div className="mt-3 rounded border border-zinc-700 bg-zinc-950/50 p-3 text-xs text-zinc-300"><p>Status: <span className="font-medium text-amber-200">{publicResult.status}</span> · {publicResult.event_count} events{publicResult.opportunity_ranking_used && <span className={`${badge} ml-2 border-indigo-500/30 text-indigo-300`}>opportunity ranking used</span>}{publicResult.competition_evidence_attempted && <span className={`${badge} ml-2 border-emerald-500/30 text-emerald-300`}>competition evidence attempted</span>}</p>{publicResult.blockers.length > 0 && <p className="mt-1 text-red-300">{publicResult.blockers.join(" · ")}</p>}{publicResult.warnings.length > 0 && <p className="mt-1 text-amber-200">{publicResult.warnings.join(" · ")}</p>}</div>}
    </section>

    {loading && <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6 text-sm text-zinc-400">Loading read-only event data…</div>}
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error.message} Check the configured server-side event source and try again.</div>}
    {!loading && !error && <>
      <div className="flex gap-2 border-b border-zinc-800">{(["timeline", "commerce", "opportunity", "competition", "shopify"] as Tab[]).map((item) => <button key={item} type="button" onClick={() => setTab(item)} className={`px-3 py-2 text-sm ${tab === item ? "border-b-2 border-indigo-400 text-indigo-300" : "text-zinc-500 hover:text-zinc-200"}`}>{item === "commerce" ? "Commerce MVP" : item === "shopify" ? "Shopify imports" : item === "opportunity" ? "Opportunity ranking" : item === "competition" ? "Competition & pricing" : "Timeline"}</button>)}</div>
      {tab === "timeline" && <section className="space-y-3"><div className="flex flex-wrap gap-2 text-xs text-zinc-400"><span>{timeline.data?.events.length ?? 0} events</span>{eventTypes.map(([type, count]) => <span key={type} className="rounded bg-zinc-800 px-2 py-1">{type}: {count}</span>)}</div><Warnings values={timeline.data?.warnings} />{timeline.data?.events.length ? <div className="overflow-x-auto rounded-lg border border-zinc-800"><table className="min-w-full text-left text-xs"><thead className="bg-zinc-900 text-zinc-500"><tr>{["Occurred", "Event", "Aggregate", "Source", "Replay hash", "Safety"].map((heading) => <th key={heading} className="px-3 py-2 font-medium">{heading}</th>)}</tr></thead><tbody>{timeline.data.events.map((event) => <tr key={event.event_id} className="border-t border-zinc-800 text-zinc-300"><td className="whitespace-nowrap px-3 py-3">{new Date(event.occurred_at * 1000).toLocaleString()}</td><td className="px-3 py-3 font-mono">{event.event_type}</td><td className="px-3 py-3">{event.aggregate_type}<br /><span className="text-zinc-500">{event.aggregate_id}</span></td><td className="px-3 py-3">{event.source}</td><td className="px-3 py-3 font-mono text-zinc-500">{event.replay_hash.slice(0, 12)}</td><td className="px-3 py-3"><div className="flex flex-wrap gap-1">{event.dry_run && <span className={`${badge} border-sky-500/30 text-sky-300`}>dry run</span>}{event.advisory && <span className={`${badge} border-violet-500/30 text-violet-300`}>advisory</span>}{event.read_only && <span className={`${badge} border-emerald-500/30 text-emerald-300`}>read-only</span>}{event.pii_redacted && <span className={`${badge} border-amber-500/30 text-amber-300`}>PII redacted</span>}</div>{event.authority_flags.length > 0 && <p className="mt-1 max-w-48 truncate text-[10px] text-zinc-500" title={event.authority_flags.join(", ")}>{event.authority_flags.join(", ")}</p>}</td></tr>)}</tbody></table></div> : <EmptyState message="No canonical events matched the current filters." />}</section>}
      {tab === "commerce" && <section className="space-y-3">{commerce.data?.runs.length ? commerce.data.runs.map((run) => <article key={run.run_id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-medium text-zinc-100">{run.query || "Commerce MVP run"}</h2><p className="mt-1 text-xs text-zinc-500">{run.run_id} · {run.event_count} events · {run.candidate_count} candidates</p></div><span className={`${badge} border-indigo-500/30 text-indigo-300`}>{run.status}</span></div><p className="mt-3 text-sm text-zinc-300">Selected candidate: {run.selected_candidate ?? "not recorded"}</p><div className="mt-3 flex flex-wrap gap-2 text-xs text-zinc-400">{[{ label: "Economics", present: run.economics_present }, { label: "Creative", present: run.creative_packet_present }, { label: "Landing page", present: run.landing_page_packet_present }, { label: "Store draft", present: run.store_draft_packet_present }, { label: "Approval", present: run.approval_packet_present }].map((item) => <span key={item.label} className="rounded bg-zinc-800 px-2 py-1">{item.label}: {item.present ? "present" : "missing"}</span>)}</div><Warnings values={[...run.warnings, ...run.blockers]} /></article>) : <EmptyState message="No Commerce MVP run summaries are available for this source." />}</section>}
      {tab === "opportunity" && <section className="space-y-4">{opportunity.data?.rankings.length ? opportunity.data.rankings.map((run) => <div key={run.run_id} className="space-y-3"><div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-zinc-800 pb-2"><h2 className="font-medium text-zinc-100">{run.query || "Opportunity ranking"}</h2><p className="text-xs text-zinc-500">{run.run_id} · {run.candidate_count} candidates scored</p></div>{run.scores.map((score) => <OpportunityScoreCard key={score.candidate_id} score={score} isTop={score.candidate_id === run.top_candidate_id} />)}</div>) : <EmptyState message="No opportunity-ranking runs are available for this source. Run a public test with 'Rank candidates with opportunity scoring' checked, or pass use_opportunity_ranking=True to run_commerce_mvp_slice()." />}</section>}
      {tab === "competition" && <section className="space-y-4">{competition.data?.summaries.length ? competition.data.summaries.map((summary) => <CompetitionSummaryCard key={summary.run_id} summary={summary} />) : <EmptyState message="No competition-intelligence runs are available for this source. Run a public test with 'Gather public competitor pricing' checked (requires opportunity ranking and the server MARKETOS_COMPETITION_EVIDENCE_LIVE gate), or pass competition_evidence to run_commerce_mvp_slice()." />}</section>}
      {tab === "shopify" && <section className="space-y-3">{shopify.data?.imports.length ? shopify.data.imports.map((item) => <article key={item.batch_id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-medium text-zinc-100">Shopify import {item.batch_id}</h2><p className="mt-1 text-xs text-zinc-500">{item.event_count} advisory events · workspace {item.workspace_id ?? "unknown"}</p></div><span className={`${badge} border-emerald-500/30 text-emerald-300`}>{item.pii_redacted ? "PII redacted" : "No PII flag"}</span></div><div className="mt-3 grid grid-cols-2 gap-2 text-sm text-zinc-300 md:grid-cols-4"><span>Products: {item.product_count}</span><span>Orders: {item.order_count}</span><span>Customers: {item.customer_count}</span><span>AOV: {item.average_order_value.toFixed(2)}</span></div><p className="mt-3 text-xs text-zinc-500">Observed revenue: {item.observed_revenue_total.toFixed(2)}. This is read-only historical context, not a forecast.</p><Warnings values={item.warnings} /></article>) : <EmptyState message="No Shopify read-only import summaries are available for this source." />}</section>}
    </>}
  </div>;
}
