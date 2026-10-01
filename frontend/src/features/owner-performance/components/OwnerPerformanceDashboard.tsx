import { useMemo, useState, type KeyboardEvent } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OwnerPerformanceReport } from "../contracts/ownerPerformanceReport.ts";
import { DEMO_OBSERVED_REPORT } from "../fixtures/demoReport.ts";
import {
  assertReportContract,
  presentCampaigns,
  presentMeasures,
  reportHasFixtureEvidence,
  textSummary,
  type MeasureDisplay,
} from "../lib/presentReport.ts";

export type DashboardPhase = "loading" | "error" | "unavailable" | "empty" | "ready";

export interface OwnerPerformanceDashboardProps {
  phase: DashboardPhase;
  report?: OwnerPerformanceReport | null;
  errorMessage?: string;
  unavailableReason?: string;
  /** When true, labelled demo content may be shown. Never implies a live connection. */
  allowDemo?: boolean;
}

function StatusNote({ tone, children }: { tone: string; children: string }) {
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
      <h3 className="text-sm font-medium text-zinc-200">{item.label}</h3>
      <p className="mt-1 text-lg text-zinc-50">
        {item.availability === "unavailable" ? "Unavailable" : `${item.amountText} ${item.currencyText}`}
      </p>
      <p className="text-xs text-zinc-300">
        Status {item.status}. Evidence {item.evidenceState}.
        {item.availability === "explicit_zero" ? " Explicit zero, not a missing value." : ""}
        {item.availability === "unavailable" ? ` Missing: ${item.missingReason}.` : ""}
      </p>
    </article>
  );
}

export default function OwnerPerformanceDashboard({
  phase,
  report,
  errorMessage,
  unavailableReason,
  allowDemo = false,
}: OwnerPerformanceDashboardProps) {
  const [showDemo, setShowDemo] = useState(false);
  const [selected, setSelected] = useState(0);
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
      ad_spend: row.chartableSpend,
      attributed_revenue: row.chartableRevenue,
    }));

  function onCampaignKey(event: KeyboardEvent<HTMLTableRowElement>, index: number) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelected(Math.min(campaigns.length - 1, index + 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelected(Math.max(0, index - 1));
    }
    if (event.key === "Home") {
      event.preventDefault();
      setSelected(0);
    }
    if (event.key === "End") {
      event.preventDefault();
      setSelected(campaigns.length - 1);
    }
  }

  return (
    <section aria-labelledby="owner-performance-heading" className="space-y-4 text-zinc-100" data-owner-performance>
      <p className="sr-only" role="status" aria-live="polite">
        {active && !contractError ? textSummary(active) : `Owner performance ${phase}.`}
      </p>
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-zinc-400">Offline reporting evidence</p>
        <h2 id="owner-performance-heading" className="text-xl font-semibold">Owner performance</h2>
        <p className="text-sm text-zinc-300">
          Amounts are shown only when the owner-performance-report-v1 contract provides them. This view does not calculate profit, claim campaign lift, or connect a platform.
        </p>
      </header>

      {phase === "loading" && <StatusNote tone="loading">Loading the performance report.</StatusNote>}
      {phase === "error" && <p role="alert" className="rounded border border-red-400/70 bg-red-950/40 px-3 py-2 text-sm">Error. {errorMessage ?? "The report could not be read."}</p>}
      {phase === "unavailable" && <StatusNote tone="unavailable">Unavailable. {unavailableReason ?? "No report endpoint is connected."}</StatusNote>}
      {phase === "empty" && <StatusNote tone="empty">No in-period lines. Empty is not zero revenue.</StatusNote>}
      {contractError && <p role="alert">Report rejected: {contractError}.</p>}

      {allowDemo && phase !== "ready" && (
        <button type="button" className="rounded border border-violet-400 px-3 py-2 text-sm" onClick={() => setShowDemo((value) => !value)}>
          {showDemo ? "Hide labelled demo" : "Show labelled demo"}
        </button>
      )}

      {showDemo && allowDemo && <StatusNote tone="demo fixture">Demo fixture. Not observed platform results.</StatusNote>}
      {active && reportHasFixtureEvidence(active) && <StatusNote tone="fixture">Fixture evidence is present. Do not treat these amounts as live results.</StatusNote>}

      {active && !contractError && phase !== "empty" && (
        <>
          <p className="text-sm">Period {active.period_start} to {active.period_end}. Currency {active.currency}. Confidence {active.evidence_quality.confidence}.</p>
          <p className="text-sm">Evidence classes: {active.evidence_quality.evidence_classes.join(", ") || "none"}.</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {measures.map((item) => <MeasureCard key={item.key} item={item} />)}
          </div>
          <p className="text-sm">Time series: not in owner-performance-report-v1. None is shown.</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="mb-2 text-left">Campaign rows from the report. Lift is never claimed.</caption>
              <thead>
                <tr>
                  <th scope="col">Campaign</th>
                  <th scope="col">Ad spend</th>
                  <th scope="col">Attributed revenue</th>
                  <th scope="col">Lift</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.length === 0 && (
                  <tr><td colSpan={4}>No campaign rows in this report.</td></tr>
                )}
                {campaigns.map((row, index) => (
                  <tr
                    key={row.campaignId}
                    tabIndex={selected === index ? 0 : -1}
                    aria-selected={selected === index}
                    onKeyDown={(event) => onCampaignKey(event, index)}
                    onClick={() => setSelected(index)}
                  >
                    <th scope="row">{row.campaignId}</th>
                    <td>{row.adSpend}</td>
                    <td>{row.attributedRevenue}</td>
                    <td>{row.lift}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {chartRows.length > 0 && (
            <div aria-hidden="true" className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartRows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="campaign" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="ad_spend" name="Reported ad spend" fill="#a1a1aa" />
                  <Bar dataKey="attributed_revenue" name="Reported attributed revenue" fill="#818cf8" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <p className="text-sm">
            Safety: read only {String(active.safety.read_only)}. Ads launched {String(active.safety.ads_launched)}. Payments created {String(active.safety.payments_created)}.
          </p>
        </>
      )}
    </section>
  );
}
