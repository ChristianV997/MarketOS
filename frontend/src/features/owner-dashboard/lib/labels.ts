/** Display copy for provider codes. Unknown codes fall back to a readable form, never a guess. */

const CODE_LABELS: Record<string, string> = {
  restricted_or_legal_category: "Restricted or legal category",
  supply_unproven: "Supply unproven",
  supplier_claim_not_verification: "Supplier claim is not verification",
  supplier_claim_is_not_independent_verification: "Supplier claim is not independent verification",
  structurally_negative_economics: "Structurally negative economics",
  economics_unavailable: "Economics unavailable",
  future_dated_evidence: "Future-dated evidence",
  no_reachable_buyer: "No reachable buyer",
};

export function humanizeCode(code: string): string {
  const known = CODE_LABELS[code];
  if (known) return known;
  const spaced = code.replace(/[_-]+/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : code;
}

const RECOMMENDATION_LABELS: Record<string, string> = {
  attractive: "Attractive",
  acceptable: "Acceptable",
  needs_evidence: "Needs evidence",
  blocked: "Blocked",
};

export function recommendationLabel(value: string | null): string {
  if (value === null) return "Not provided";
  return RECOMMENDATION_LABELS[value] ?? humanizeCode(value);
}

const ECONOMICS_LINE_LABELS: Record<string, string> = {
  net_sales: "Net sales",
  product_cost: "Product cost",
  supplier_shipping: "Supplier shipping",
  domestic_shipping: "Domestic shipping",
  international_shipping: "International shipping",
  duty: "Duty",
  tax: "Tax",
  brokerage: "Brokerage",
  payment_fees: "Payment fees",
  platform_fees: "Platform fees",
  marketplace_fees: "Marketplace fees",
  affiliate_fees: "Affiliate fees",
  return_reserve: "Return reserve",
  defect_reserve: "Defect reserve",
  warranty_reserve: "Warranty reserve",
  support_reserve: "Support reserve",
  chargeback_reserve: "Chargeback reserve",
  fx_reserve: "FX reserve",
  cac: "Customer acquisition cost (CAC)",
  contribution_before_cac: "Contribution before CAC",
  contribution_after_cac: "Contribution after CAC",
  break_even_cac: "Break-even CAC",
  target_cac: "Target CAC",
  cash_required_per_order: "Cash required per order",
  refund_lag_exposure: "Refund-lag exposure",
  expected_return_cost: "Expected return cost",
  refund_loss: "Refund loss",
  defect_cost: "Defect cost",
  warranty_cost: "Warranty cost",
};

export function economicsLineLabel(key: string): string {
  return ECONOMICS_LINE_LABELS[key] ?? humanizeCode(key);
}

export const RATIO_LABELS: Record<string, string> = {
  contribution_margin: "Contribution margin",
  contribution_margin_after_cac: "Contribution margin after CAC",
  break_even_roas: "Break-even ROAS",
  target_roas: "Target ROAS",
};

export const BASIS_LABELS = {
  observed: "Observed",
  manual: "Manual input",
  derived: "Derived",
  assumed: "Assumption",
  fixture: "Fixture",
  unknown: "Unknown basis",
} as const;

const SCENARIO_LABELS: Record<string, string> = {
  best: "Best case",
  base: "Base case",
  worst: "Worst case",
};

export function scenarioLabel(name: string): string {
  return SCENARIO_LABELS[name] ?? humanizeCode(name);
}

export const UNRANKED_LABELS = {
  needs_evidence: "Needs evidence",
  blocked: "Blocked by a fatal gate",
  ready_unscored: "Ready, but the provider produced no comparable score",
  not_ranked: "Not ranked by the provider",
} as const;
