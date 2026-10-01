/** Contract pinned to MarketOS PR #368 head 17f0c6caa769ea13a3635b28dbb70313802da2fa.
 * Schema owner-performance-report-v1. There is no time-series field.
 */
export const OWNER_PERFORMANCE_SCHEMA = "owner-performance-report-v1" as const;
export const CONTRACT_HEAD = "17f0c6caa769ea13a3635b28dbb70313802da2fa";

export const MEASURE_KEYS = [
  "revenue",
  "refunds",
  "product_cost",
  "shipping_cost",
  "fees",
  "ad_spend",
  "contribution",
  "realized_profit",
] as const;

export type MeasureKey = (typeof MEASURE_KEYS)[number];

export const MEASURE_LABELS: Record<MeasureKey, string> = {
  revenue: "Revenue",
  refunds: "Refunds",
  product_cost: "Product cost",
  shipping_cost: "Shipping cost",
  fees: "Fees",
  ad_spend: "Ad spend",
  contribution: "Contribution",
  realized_profit: "Realized profit",
};

export type EvidenceClass = "observed" | "manual" | "fixture" | "modeled" | "assumed";
export type MeasureStatus = "observed" | "fixture" | "modeled" | "mixed" | "derived" | "unavailable";

export interface MoneyView {
  status: string;
  amount: string | null;
  currency: string | null;
  provenance: string;
  evidence_state: string;
  missing_reason: string | null;
  source?: string;
  exchange_rate?: string;
  exchange_rate_timestamp?: string;
  uncertainty?: string;
  tax_inclusion_state?: string;
}

export interface CampaignRow {
  campaign_id: string;
  ad_spend: MoneyView;
  attributed_revenue: MoneyView;
  lift: MoneyView;
  causal_attribution: boolean;
}

export interface OwnerPerformanceReport {
  schema: typeof OWNER_PERFORMANCE_SCHEMA;
  period_start: string;
  period_end: string;
  currency: string;
  revenue: MoneyView;
  refunds: MoneyView;
  product_cost: MoneyView;
  shipping_cost: MoneyView;
  fees: MoneyView;
  ad_spend: MoneyView;
  contribution: MoneyView;
  realized_profit: MoneyView;
  campaigns: CampaignRow[];
  missing_inputs: string[];
  explicit_zeros: string[];
  evidence_quality: {
    line_count: number;
    excluded_before_period: number;
    excluded_after_period: number;
    evidence_classes: string[];
    confidence: string;
    claims: {
      campaign_lift: boolean;
      realized_profit: boolean;
      causal_attribution: boolean;
    };
  };
  authorities: { economics: string; reporting: string };
  safety: {
    read_only: boolean;
    network_calls: boolean;
    provider_calls: boolean;
    ads_launched: boolean;
    payments_created: boolean;
    publishing: boolean;
    launch_authorized: boolean;
  };
  fingerprint: string;
}

export function isMeasureKey(value: string): value is MeasureKey {
  return (MEASURE_KEYS as readonly string[]).includes(value);
}
