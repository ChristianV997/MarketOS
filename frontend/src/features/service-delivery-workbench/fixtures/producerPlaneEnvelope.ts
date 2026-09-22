import { PRIORITY_SERVICE_IDS, SERVICE_DELIVERY_PLANE_REPORT_VERSION } from "../contracts/serviceEngagementProjection.ts";

const LIFECYCLES = [
  "data_inadequate",
  "draft_ready",
  "client_review",
  "revision_requested",
  "approved",
  "delivered",
  "cancelled",
  "rejected",
  "renewal_candidate",
  "upsell_candidate",
] as const;

/** Sanitized #275 `service-delivery-plane-v1` envelope for frontend consume tests. */
export function buildProducerPlaneEnvelope(overrides: Record<string, unknown> = {}) {
  const engagements = LIFECYCLES.map((lifecycle, index) => ({
    engagement_id: `eng-prod-${index + 1}`,
    client_id: `client-${index + 1}`,
    workspace_id: `ws-client-${index + 1}`,
    package_id: [
      "client_product_validation_sprint",
      "client_unit_economics_diagnostic",
      "client_launch_draft_pack",
      "client_managed_acquisition_diagnostic",
    ][index % 4],
    service_id: PRIORITY_SERVICE_IDS[index % 4],
    lifecycle_state: lifecycle,
    data_quality_state: lifecycle === "data_inadequate" ? "data_inadequate" : "adequate",
    missing_data: lifecycle === "data_inadequate" ? ["product_offer_identity"] : [],
    stale: false,
    intake: {
      client_id: `client-${index + 1}`,
      display_name: `Producer client ${index + 1}`,
      workspace_id: `ws-client-${index + 1}`,
      contact_channel: "not_collected",
      fields: [{
        field_id: "product_offer_identity",
        label: "Product or offer identity",
        status: lifecycle === "data_inadequate" ? "missing" : "received",
        client_must_provide: lifecycle === "data_inadequate"
          ? "Provide Product or offer identity as a client-safe record."
          : "Already recorded as a display copy.",
      }],
    },
    eligibility: {
      eligible: lifecycle !== "rejected" && lifecycle !== "cancelled" && lifecycle !== "data_inadequate",
      data_inadequate: lifecycle === "data_inadequate",
      reasons: lifecycle === "data_inadequate" ? ["missing product identity"] : [],
      required_from_client: lifecycle === "data_inadequate"
        ? [{
          field: "product_offer_identity",
          why: "Product or offer identity is required before analysis can proceed.",
          how_to_provide: "Provide Product or offer identity as a client-safe export.",
        }]
        : [],
    },
    evidence_set: [{
      evidence_id: `ev-${index + 1}`,
      title: "Sanitized producer evidence",
      evidence_class: lifecycle === "data_inadequate" ? "unavailable" : "manual_import",
      summary: "Producer copy. Not live proof.",
      collected_at: "2026-09-18",
    }],
    economics: {
      authority: "backend_service_economics",
      frontend_calculates: false,
      fee: {
        amount_label: "1200.00",
        currency: index === 3 ? "MXN" : "USD",
        evidence_class: "assumption",
        source: "backend_service_economics",
        display_only: true,
      },
      contribution: lifecycle === "approved" || lifecycle === "delivered"
        ? {
          amount_label: "410.00",
          currency: index === 3 ? "MXN" : "USD",
          evidence_class: "assumption",
          source: "backend_service_economics",
          display_only: true,
        }
        : null,
      contribution_unavailable_reason: lifecycle === "approved" || lifecycle === "delivered"
        ? null
        : "No sanitized contribution copy was supplied.",
      planning_assumption_note: "Price, CAC, ROAS, and contribution labels are planning assumptions unless marked live_validated by the backend.",
    },
    financial_readiness: {
      ready: lifecycle !== "data_inadequate",
      missing: lifecycle === "data_inadequate" ? ["product_offer_identity"] : [],
      note: "Financial figures are display copies only. The frontend does not calculate contribution.",
    },
    capacity: {
      state: "unavailable",
      message: "Capacity signal unavailable.",
      concurrent_label: null,
    },
    next_best_action: {
      action: lifecycle === "data_inadequate"
        ? "Review intake and data quality before proceeding."
        : "Review the sanitized engagement copy.",
      owner: lifecycle === "data_inadequate" ? "client" : "operator",
      executes_live_action: false,
      rationale: "This workbench is read-only and does not execute CompanyOS transitions.",
    },
    deliverable_ids: [`del-${index + 1}`],
    renewal_state: lifecycle === "renewal_candidate" ? "eligible" : lifecycle === "upsell_candidate" ? "upsell_review" : "not_applicable",
    approval_state: lifecycle === "approved" || lifecycle === "delivered" || lifecycle === "renewal_candidate" || lifecycle === "upsell_candidate" ? "approved" : "not_requested",
    delivery_state: lifecycle === "delivered" || lifecycle === "renewal_candidate" || lifecycle === "upsell_candidate" ? "complete" : "not_started",
  }));

  return {
    report_version: SERVICE_DELIVERY_PLANE_REPORT_VERSION,
    schema_version: SERVICE_DELIVERY_PLANE_REPORT_VERSION,
    availability: "manual_import",
    generated_at: "offline-deterministic",
    read_only: true,
    network_calls: false,
    mutated: false,
    diagnostics: ["#275 producer envelope for frontend consume tests"],
    engagements,
    ...overrides,
  };
}
