import type { OwnerPerformanceReport } from "../contracts/ownerPerformanceReport.ts";

function money(amount: string | null, status: string, missing: string | null, currency = "USD") {
  if (amount === null) {
    return {
      status,
      amount: null,
      currency: null,
      provenance: "unavailable",
      evidence_state: "missing",
      missing_reason: missing,
    };
  }
  return {
    status,
    amount,
    currency,
    source: status,
    provenance: status,
    evidence_state: status === "derived" ? "derived" : status,
    missing_reason: null,
    exchange_rate: "unknown",
    exchange_rate_timestamp: "unknown",
    uncertainty: "unknown",
    tax_inclusion_state: "unknown",
  };
}

/** Labelled demo packet matching PR #368 complete observed fixture. Not live data. */
export const DEMO_OBSERVED_REPORT: OwnerPerformanceReport = {
  schema: "owner-performance-report-v1",
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  currency: "USD",
  revenue: money("100.00", "observed", null),
  refunds: money("10.00", "observed", null),
  product_cost: money("40.00", "observed", null),
  shipping_cost: money("5.00", "observed", null),
  fees: money("3.00", "observed", null),
  ad_spend: money("12.00", "observed", null),
  contribution: money("42.00", "derived", null),
  realized_profit: money("30.00", "derived", null),
  campaigns: [
    {
      campaign_id: "camp-a",
      ad_spend: money("12.00", "observed", null),
      attributed_revenue: money("100.00", "observed", null),
      lift: money(null, "unavailable", "causal_lift_unsupported"),
      causal_attribution: false,
    },
  ],
  missing_inputs: [],
  explicit_zeros: [],
  evidence_quality: {
    line_count: 6,
    excluded_before_period: 0,
    excluded_after_period: 0,
    evidence_classes: ["observed"],
    confidence: "high",
    claims: { campaign_lift: false, realized_profit: true, causal_attribution: false },
  },
  authorities: {
    economics: "backend.economics.kernel",
    reporting: "backend.commerce.owner_performance_report.build_owner_performance_report",
  },
  safety: {
    read_only: true,
    network_calls: false,
    provider_calls: false,
    ads_launched: false,
    payments_created: false,
    publishing: false,
    launch_authorized: false,
  },
  fingerprint: "demo-observed-not-a-live-fingerprint",
};

export const DEMO_PARTIAL_REPORT: OwnerPerformanceReport = {
  ...DEMO_OBSERVED_REPORT,
  refunds: money(null, "unavailable", "refunds_absent"),
  contribution: money(null, "unavailable", "incomplete_contribution_inputs"),
  realized_profit: money(null, "unavailable", "incomplete_profit_inputs"),
  missing_inputs: ["refunds_absent", "refunds_required_for_contribution"],
  explicit_zeros: [],
  evidence_quality: {
    ...DEMO_OBSERVED_REPORT.evidence_quality,
    evidence_classes: ["fixture", "observed"],
    confidence: "partial",
    claims: { campaign_lift: false, realized_profit: false, causal_attribution: false },
  },
  fingerprint: "demo-partial-not-a-live-fingerprint",
};
