import {
  MEASURE_KEYS,
  MEASURE_LABELS,
  OWNER_PERFORMANCE_SCHEMA,
  type MeasureKey,
  type MoneyView,
  type OwnerPerformanceReport,
} from "../contracts/ownerPerformanceReport.ts";

export interface MeasureDisplay {
  key: MeasureKey;
  label: string;
  availability: "available" | "explicit_zero" | "unavailable";
  amountText: string;
  currencyText: string;
  status: string;
  evidenceState: string;
  provenance: string;
  missingReason: string | null;
  summary: string;
}

export interface CampaignDisplay {
  campaignId: string;
  adSpend: string;
  attributedRevenue: string;
  lift: string;
  causalAttribution: "not claimed";
  chartableSpend: string | null;
  chartableRevenue: string | null;
}

const ZERO = /^-?(?:0+|0+\.0+)$/;

export function isExplicitZero(amount: string | null, key: MeasureKey, report: OwnerPerformanceReport): boolean {
  return amount !== null && ZERO.test(amount) && (report.explicit_zeros ?? []).includes(key);
}

export function presentMeasure(key: MeasureKey, view: MoneyView | undefined | null, report: OwnerPerformanceReport): MeasureDisplay {
  const label = MEASURE_LABELS[key];
  if (!view || view.amount === null || view.status === "unavailable") {
    const reason = view?.missing_reason ?? "not reported";
    return {
      key,
      label,
      availability: "unavailable",
      amountText: "Unavailable",
      currencyText: "\u2014",
      status: view?.status || "unavailable",
      evidenceState: view?.evidence_state || "missing",
      provenance: view?.provenance || "unavailable",
      missingReason: reason,
      summary: `${label}: unavailable (${reason}). Not zero.`,
    };
  }
  if (isExplicitZero(view.amount, key, report)) {
    return {
      key,
      label,
      availability: "explicit_zero",
      amountText: view.amount,
      currencyText: view.currency ?? report.currency,
      status: view.status,
      evidenceState: view.evidence_state,
      provenance: view.provenance,
      missingReason: null,
      summary: `${label}: explicit zero ${view.amount} ${view.currency ?? report.currency}, status ${view.status}.`,
    };
  }
  return {
    key,
    label,
    availability: "available",
    amountText: view.amount,
    currencyText: view.currency ?? report.currency,
    status: view.status,
    evidenceState: view.evidence_state,
    provenance: view.provenance,
    missingReason: null,
    summary: `${label}: ${view.amount} ${view.currency ?? report.currency}, status ${view.status}, evidence ${view.evidence_state}.`,
  };
}

export function presentMeasures(report: OwnerPerformanceReport): MeasureDisplay[] {
  return MEASURE_KEYS.map((key) => presentMeasure(key, report[key], report));
}

export function presentCampaigns(report: OwnerPerformanceReport): CampaignDisplay[] {
  return (report.campaigns ?? []).map((row) => ({
    campaignId: row.campaign_id,
    adSpend: row.ad_spend?.amount === null || row.ad_spend?.amount === undefined
      ? "Unavailable"
      : `${row.ad_spend.amount} ${row.ad_spend.currency ?? report.currency}`,
    attributedRevenue: row.attributed_revenue?.amount === null || row.attributed_revenue?.amount === undefined
      ? "Unavailable"
      : `${row.attributed_revenue.amount} ${row.attributed_revenue.currency ?? report.currency}`,
    lift: "Not claimed. Causal lift is unsupported.",
    causalAttribution: "not claimed",
    chartableSpend: row.ad_spend?.amount ?? null,
    chartableRevenue: row.attributed_revenue?.amount ?? null,
  }));
}

export function reportHasFixtureEvidence(report: OwnerPerformanceReport): boolean {
  return (report.evidence_quality?.evidence_classes ?? []).includes("fixture")
    || presentMeasures(report).some((item) => item.status === "fixture");
}

export function assertReportContract(value: unknown): OwnerPerformanceReport {
  if (!value || typeof value !== "object") throw new Error("report_not_object");
  const report = value as OwnerPerformanceReport;
  if (report.schema !== OWNER_PERFORMANCE_SCHEMA) throw new Error("schema_mismatch");
  if (report.evidence_quality?.claims?.campaign_lift !== false) throw new Error("lift_claim_rejected");
  if (report.evidence_quality?.claims?.causal_attribution !== false) throw new Error("attribution_claim_rejected");
  if (!Array.isArray(report.campaigns)) throw new Error("campaigns_missing");
  for (const campaign of report.campaigns) {
    if (campaign.causal_attribution !== false) throw new Error("campaign_attribution_claim_rejected");
    if (campaign.lift && campaign.lift.status !== "unavailable") throw new Error("campaign_lift_claim_rejected");
  }
  if (!report.safety || report.safety.read_only !== true) throw new Error("read_only_required");
  if (report.safety.launch_authorized === true) throw new Error("launch_authorized_rejected");
  if (report.safety.ads_launched === true) throw new Error("ads_launched_rejected");
  if (report.safety.publishing === true) throw new Error("publishing_rejected");
  if (report.safety.payments_created === true) throw new Error("payments_created_rejected");
  return report;
}

export function textSummary(report: OwnerPerformanceReport): string {
  const measures = presentMeasures(report).map((item) => item.summary).join(" ");
  const claims = "Campaign lift is not claimed. Causal attribution is not claimed. This is offline reporting evidence.";
  return `${report.period_start} to ${report.period_end}. ${measures} ${claims}`;
}
