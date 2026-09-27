/**
 * Future-facing frontend adapter contract for a sanitized service-engagement
 * projection. This is not a second backend packet and does not calculate
 * ServiceEconomics. Authoritative money values, if present, are display copies.
 */

export const SERVICE_ENGAGEMENT_PROJECTION_VERSION = "service-engagement-projection-v1";
export const SERVICE_DELIVERY_PLANE_REPORT_VERSION = "service-delivery-plane-v1";
export const CLIENT_SAFE_SERVICE_EXPORT_VERSION = "client-safe-service-export-v1";
export const FUTURE_WORKBENCH_PATH = "/api/service-delivery/workbench";

export const PRIORITY_SERVICE_IDS = [
  "product-validation-sprint",
  "unit-economics-cac-roas-diagnostic",
  "launch-draft-pack",
  "managed-acquisition-cro",
] as const;

export type PriorityServiceId = (typeof PRIORITY_SERVICE_IDS)[number];

export const PRIORITY_SERVICE_LABELS: Record<PriorityServiceId, string> = {
  "product-validation-sprint": "Product Validation Sprint",
  "unit-economics-cac-roas-diagnostic": "Unit Economics + CAC/ROAS Diagnostic",
  "launch-draft-pack": "Launch Draft Pack",
  "managed-acquisition-cro": "Managed Acquisition and CRO",
};

export const LIFECYCLE_STATES = [
  "intake",
  "screening",
  "data_inadequate",
  "eligible",
  "scoped",
  "evidence_collection",
  "analysis",
  "draft_ready",
  "client_review",
  "revision_requested",
  "approved",
  "delivered",
  "renewal_candidate",
  "upsell_candidate",
  "paused",
  "cancelled",
  "rejected",
  "unavailable",
] as const;

export type LifecycleState = (typeof LIFECYCLE_STATES)[number];

export const EVIDENCE_CLASSES = [
  "observed",
  "derived",
  "assumption",
  "supplier_claimed",
  "supplier_documented",
  "fixture",
  "manual_import",
  "simulated",
  "unavailable",
  "live_validated",
] as const;

export type EvidenceClass = (typeof EVIDENCE_CLASSES)[number];

export const SURFACE_STATES = [
  "empty",
  "blocked",
  "unavailable",
  "loading",
  "stale",
  "partial",
  "success",
] as const;

export type SurfaceState = (typeof SURFACE_STATES)[number];

export type DisplayMoney = {
  amount_label: string;
  currency: string;
  evidence_class: EvidenceClass;
  source: "backend_service_economics" | "unavailable";
  display_only: true;
};

export type IntakeField = {
  field_id: string;
  label: string;
  status: "received" | "missing" | "stale" | "conflicting";
  client_must_provide: string;
};

export type EvidenceItem = {
  evidence_id: string;
  title: string;
  evidence_class: EvidenceClass;
  summary: string;
  collected_at: string | null;
};

export type DeliverableItem = {
  deliverable_id: string;
  name: string;
  status: "not_started" | "in_progress" | "blocked" | "draft_ready" | "client_safe" | "rejected";
  blocked_reason: string | null;
};

export type CreativeAssetRequest = {
  skill_id: "product-photoshoot" | "marketplace-cards" | "brandkit" | "video-explainer";
  title: string;
  status: "draft" | "unavailable";
  generation_enabled: false;
  publication_enabled: false;
  note: string;
};

export type ServiceEconomicsSummary = {
  authority: "backend_service_economics";
  frontend_calculates: false;
  fee: DisplayMoney | null;
  contribution: DisplayMoney | null;
  contribution_unavailable_reason: string | null;
  planning_assumption_note: string;
};

export type CapacitySignal = {
  state: "ok" | "warning" | "blocked" | "unavailable";
  message: string;
  concurrent_label: string | null;
};

export type ClientIntake = {
  client_id: string;
  display_name: string;
  workspace_id: string;
  contact_channel: string;
  fields: IntakeField[];
};

export type EligibilityPanel = {
  eligible: boolean;
  data_inadequate: boolean;
  reasons: string[];
  required_from_client: { field: string; why: string; how_to_provide: string }[];
};

export type FinancialReadiness = {
  ready: boolean;
  missing: string[];
  note: string;
};

export type NextBestAction = {
  action: string;
  owner: "operator" | "client" | "blocked";
  executes_live_action: false;
  rationale: string;
};

export type ServiceEngagement = {
  engagement_id: string;
  service_id: PriorityServiceId;
  lifecycle_state: LifecycleState;
  intake: ClientIntake;
  eligibility: EligibilityPanel;
  evidence: EvidenceItem[];
  financial_readiness: FinancialReadiness;
  deliverables: DeliverableItem[];
  economics: ServiceEconomicsSummary;
  capacity: CapacitySignal;
  assumptions: string[];
  missing_data: string[];
  next_best_action: NextBestAction;
  creative_assets: CreativeAssetRequest[];
  private_operator_notes: string | null;
  internal_prompt: string | null;
  internal_formula: string | null;
  updated_at: string;
  stale: boolean;
  /** Copied #261/#275 labels. Display only; not a workflow engine. */
  renewal_state: string | null;
  approval_state: string | null;
  delivery_state: string | null;
};

export type ServiceEngagementProjection = {
  schema_version: typeof SERVICE_ENGAGEMENT_PROJECTION_VERSION;
  availability: "fixture" | "unavailable" | "partial" | "manual_import";
  live_endpoint: typeof FUTURE_WORKBENCH_PATH;
  live_endpoint_status: "unavailable" | "available_read_only";
  read_only: true;
  generated_at: string;
  engagements: ServiceEngagement[];
  diagnostics: string[];
  input_contract: typeof SERVICE_ENGAGEMENT_PROJECTION_VERSION | typeof SERVICE_DELIVERY_PLANE_REPORT_VERSION | "unknown";
};

export type ClientSafeServiceExport = {
  export_version: typeof CLIENT_SAFE_SERVICE_EXPORT_VERSION;
  accepted: boolean;
  rejection_reason: string | null;
  read_only: true;
  mutated: false;
  payload: Record<string, unknown> | null;
};
