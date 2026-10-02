import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OwnerPerformanceReport } from "../contracts/ownerPerformanceReport.ts";
import { OwnerActivityPanel } from "./OwnerActivityPanel.tsx";
import { OWNER_ACTIVITY_UNAVAILABLE } from "../lib/ownerActivity.ts";
import { DEMO_OBSERVED_REPORT } from "../fixtures/demoReport.ts";
import { useOwnerPerformance } from "../hooks/useOwnerPerformance.ts";
import {
  assertReportContract,
  presentCampaigns,
  presentMeasures,
  reportHasFixtureEvidence,
  textSummary,
  type MeasureDisplay,
} from "../lib/presentReport.ts";

export type DashboardPhase = "loading" | "error" | "unavailable" | "empty" | "ready" | "auth";

export interface OwnerPerformanceDashboardProps {
  phase?: DashboardPhase;
  report?: OwnerPerformanceReport | null;
  errorMessage?: string;
  unavailableReason?: string;
  authMessage?: string;
  isStale?: boolean;
  staleMessage?: string;
  /** When true, labelled demo content may be shown. Never implies a live connection. */
  allowDemo?: boolean;
}

function StatusNote({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <p role="status" data-tone={tone} className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-sm text-zinc-100">
      <span className="mr-2 rounded border border-zinc-500 px-1.5 py-0.5 text-xs uppercase tracking-wide">{tone}</span>
      {children}
    </p>
  );
}

function MeasureCard({ item }: { item: MeasureDisplay }) {
  return (
    <article className="rounded-lg border border-zinc-700 bg-zinc-950 p-3" aria-label={item.summary}>
      <div className="flex items-center justify-between gap-1">
        <h3 className="text-sm font-medium text-zinc-200">{item.label}</h3>
        <span className="rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[11px] uppercase tracking-wider text-zinc-300">
          {item.status}
        </span>
      </div>
      <p className="mt-1 text-lg text-zinc-50 font-semibold">
        {item.availability === "unavailable" ? "Unavailable" : `${item.amountText} ${item.currencyText}`}
      </p>
      <div className="text-xs text-zinc-300 mt-1 space-y-0.5">
        <p>
          <span className="text-zinc-400">Evidence:</span> {item.evidenceState}
          {item.provenance && item.provenance !== item.status ? ` · Provenance: ${item.provenance}` : ""}
        </p>
        {item.availability === "explicit_zero" && (
          <p className="text-emerald-400 font-medium">Explicit zero, not a missing value.</p>
        )}
        {item.availability === "unavailable" && (
          <p className="text-amber-300/90">Missing: {item.missingReason}.</p>
        )}
      </div>
    </article>
  );
}

export function OwnerPerformanceDashboardView({
  phase = "unavailable",
  report = null,
  errorMessage,
  unavailableReason,
  authMessage,
  isStale = false,
  staleMessage,
  allowDemo = false,
}: OwnerPerformanceDashboardProps) {
  const [showDemo, setShowDemo] = useState(false);
  const [selected, setSelected] = useState(0);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);
  const active = phase === "ready" && report ? report : showDemo && allowDemo ? DEMO_OBSERVED_REPORT : null;
  const contractError = useMemo(() => {
    if (!active) return null;
    try {
      assertReportContract(active);
      return null;
    } catch (error) {
      return error instanceof Error ? error.message : "invalid_report";
    }
  }, [active]);
  const measures = active && !contractError ? presentMeasures(active) : [];
  const campaigns = active && !contractError ? presentCampaigns(active) : [];
  const chartRows = campaigns
    .filter((row) => row.chartableSpend !== null || row.chartableRevenue !== null)
    .map((row) => ({
      campaign: row.campaignId,
      ad_spend: row.chartableSpend !== null ? Number(row.chartableSpend) : null,
      attributed_revenue: row.chartableRevenue !== null ? Number(row.chartableRevenue) : null,
    }));

  function onCampaignKey(event: KeyboardEvent<HTMLTableRowElement>, index: number) {
    let targetIndex: number | null = null;
    if (event.key === "ArrowDown") targetIndex = Math.min(campaigns.length - 1, index + 1);
    if (event.key === "ArrowUp") targetIndex = Math.max(0, index - 1);
    if (event.key === "Home") targetIndex = 0;
    if (event.key === "End") targetIndex = campaigns.length - 1;

    if (targetIndex !== null) {
      event.preventDefault();
      setSelected(targetIndex);
      rowRefs.current[targetIndex]?.focus();
    }
  }

  return (
    <section aria-labelledby="owner-performance-heading" className="space-y-4 text-zinc-100 w-full min-w-0" data-owner-performance>
      {phase === "ready" && active && !contractError && (
        <p className="sr-only" role="status" aria-live="polite">
          {textSummary(active)}
        </p>
      )}
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-zinc-400">Offline reporting evidence</p>
        <h2 id="owner-performance-heading" className="text-xl font-semibold">Owner performance</h2>
        <p className="text-sm text-zinc-300">
          Amounts are shown only when the owner-performance-report-v1 contract provides them. This view does not calculate profit, claim campaign lift, or connect a platform.
        </p>
      </header>

      <OwnerActivityPanel activity={OWNER_ACTIVITY_UNAVAILABLE} />

      {phase === "loading" && <StatusNote tone="loading">Loading the performance report.</StatusNote>}
      {phase === "auth" && (
        <p role="alert" className="rounded border border-amber-500/70 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          <span className="mr-2 rounded border border-amber-500 px-1.5 py-0.5 text-xs uppercase tracking-wide">Authentication required</span>
          {authMessage ?? "Authentication is required to view the owner performance report."}
        </p>
      )}
      {phase === "error" && (
        <p role="alert" className="rounded border border-red-400/70 bg-red-950/40 px-3 py-2 text-sm text-red-200">
          <span className="mr-2 rounded border border-red-500 px-1.5 py-0.5 text-xs uppercase tracking-wide">Error</span>
          {errorMessage ?? "The report could not be read."}
        </p>
      )}
      {phase === "unavailable" && (
        <StatusNote tone="unavailable">
          Unavailable. {unavailableReason ?? "Backend route GET /api/owner/performance is not yet mounted. Contract dependency: owner-performance-report-v1 (PR #368)."}
        </StatusNote>
      )}
      {phase === "empty" && <StatusNote tone="empty">No in-period lines. Empty is not zero revenue.</StatusNote>}
      {isStale && active && (
        <StatusNote tone="stale">
          {staleMessage ?? "Cached report may be stale. Background refresh pending or unavailable."}
        </StatusNote>
      )}
      {contractError && (
        <p role="alert" className="rounded border border-red-500/70 bg-red-950/40 px-3 py-2 text-sm text-red-200">
          Report rejected: {contractError}.
        </p>
      )}

      {allowDemo && phase !== "ready" && (
        <button
          type="button"
          aria-pressed={showDemo}
          className="rounded border border-violet-400 px-3 py-2 text-sm hover:bg-violet-950/30 transition-colors"
          onClick={() => setShowDemo((value) => !value)}
        >
          {showDemo ? "Hide labelled demo" : "Show labelled demo"}
        </button>
      )}

      {showDemo && allowDemo && <StatusNote tone="demo fixture">Demo fixture. Not observed platform results.</StatusNote>}
      {active && reportHasFixtureEvidence(active) && (
        <StatusNote tone="fixture">Fixture evidence is present. Do not treat these amounts as live results.</StatusNote>
      )}

      {active && !contractError && phase !== "empty" && (
        <>
          <div className="space-y-1 text-sm text-zinc-300">
            <p>Period {active.period_start} to {active.period_end}. Currency {active.currency}. Confidence {active.evidence_quality.confidence}.</p>
            <p>Evidence classes: {active.evidence_quality.evidence_classes.join(", ") || "none"}.</p>
          </div>

          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
            {measures.map((item) => (
              <MeasureCard key={item.key} item={item} />
            ))}
          </div>

          <p className="text-sm text-zinc-400">Time series: not in owner-performance-report-v1. None is shown.</p>

          <div className="overflow-x-auto rounded border border-zinc-800">
            <table role="grid" className="w-full text-left text-sm">
              <caption className="mb-2 text-left px-2 pt-2 text-xs text-zinc-400">
                Campaign rows from the report. Lift is never claimed. Causal attribution is not claimed.
              </caption>
              <thead className="bg-zinc-900 text-zinc-300">
                <tr role="row">
                  <th scope="col" className="px-3 py-2">Campaign</th>
                  <th scope="col" className="px-3 py-2">Ad spend</th>
                  <th scope="col" className="px-3 py-2">Attributed revenue</th>
                  <th scope="col" className="px-3 py-2">Lift</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {campaigns.length === 0 && (
                  <tr role="row">
                    <td colSpan={4} className="px-3 py-3 text-zinc-400">No campaign rows in this report.</td>
                  </tr>
                )}
                {campaigns.map((row, index) => (
                  <tr
                    key={row.campaignId}
                    ref={(el) => { rowRefs.current[index] = el; }}
                    role="row"
                    tabIndex={selected === index ? 0 : -1}
                    aria-selected={selected === index}
                    onKeyDown={(event) => onCampaignKey(event, index)}
                    onClick={() => {
                      setSelected(index);
                      rowRefs.current[index]?.focus();
                    }}
                    className={`cursor-pointer transition-colors ${
                      selected === index ? "bg-zinc-800/80 ring-1 ring-inset ring-indigo-500" : "hover:bg-zinc-900/60"
                    }`}
                  >
                    <th scope="row" className="px-3 py-2 font-medium">{row.campaignId}</th>
                    <td className="px-3 py-2">{row.adSpend}</td>
                    <td className="px-3 py-2">{row.attributedRevenue}</td>
                    <td className="px-3 py-2 text-zinc-400">{row.lift}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {chartRows.length > 0 && (
            <div className="space-y-2">
              <div aria-hidden="true" className="h-56 sm:h-64 w-full min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartRows} margin={{ top: 10, right: 10, left: 0, bottom: 20 }}>
                    <defs>
                      <pattern id="spend-stripes" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                        <rect width="8" height="8" fill="#3f3f46" />
                        <line x1="0" y1="0" x2="0" y2="8" stroke="#f4f4f5" strokeWidth="2.5" />
                      </pattern>
                      <pattern id="revenue-dots" width="8" height="8" patternUnits="userSpaceOnUse">
                        <rect width="8" height="8" fill="#312e81" />
                        <circle cx="4" cy="4" r="2" fill="#c7d2fe" />
                      </pattern>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="campaign" stroke="#a1a1aa" fontSize={12} tickLine={false} />
                    <YAxis
                      stroke="#a1a1aa"
                      fontSize={12}
                      tickLine={false}
                      tickFormatter={(val) => `${val} ${active.currency}`}
                    />
                    <Tooltip contentStyle={{ backgroundColor: "#09090b", borderColor: "#3f3f46", color: "#f4f4f5", borderRadius: "6px" }} />
                    <Legend wrapperStyle={{ paddingTop: "8px", fontSize: "12px", color: "#d4d4d8" }} />
                    <Bar dataKey="ad_spend" name="Reported ad spend" fill="url(#spend-stripes)" stroke="#e4e4e7" strokeWidth={1.5} />
                    <Bar dataKey="attributed_revenue" name="Reported attributed revenue" fill="url(#revenue-dots)" stroke="#a5b4fc" strokeWidth={1.5} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-zinc-400">
                Visual comparison: reported ad spend (striped pattern with light border) vs. reported attributed revenue (dotted pattern with indigo border) per campaign. Full data is available in the accessible table above.
              </p>
            </div>
          )}

          <p className="text-xs text-zinc-400">
            Safety: read only {String(active.safety.read_only)}. Ads launched {String(active.safety.ads_launched)}. Payments created {String(active.safety.payments_created)}.
          </p>
        </>
      )}
    </section>
  );
}

function LiveOwnerPerformanceDashboard(props: OwnerPerformanceDashboardProps) {
  // Keep the dashboard unavailable until the canonical backend route is
  // mounted. The hook supports an explicit opt-in for that future seam.
  const query = useOwnerPerformance();
  return (
    <OwnerPerformanceDashboardView
      {...props}
      phase={query.phase}
      report={query.report}
      errorMessage={query.errorMessage}
      unavailableReason={query.unavailableReason}
      authMessage={query.authMessage}
      isStale={query.isStale}
      staleMessage={query.staleMessage}
    />
  );
}

export default function OwnerPerformanceDashboard(props: OwnerPerformanceDashboardProps) {
  if (props.phase !== undefined || props.report !== undefined) {
    return <OwnerPerformanceDashboardView {...props} phase={props.phase ?? "ready"} />;
  }
  return <LiveOwnerPerformanceDashboard {...props} />;
}
