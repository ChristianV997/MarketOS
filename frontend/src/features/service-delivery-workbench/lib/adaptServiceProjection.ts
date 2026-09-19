import {
  EVIDENCE_CLASSES,
  FUTURE_WORKBENCH_PATH,
  LIFECYCLE_STATES,
  PRIORITY_SERVICE_IDS,
  SERVICE_DELIVERY_PLANE_REPORT_VERSION,
  SERVICE_ENGAGEMENT_PROJECTION_VERSION,
  type EvidenceClass,
  type LifecycleState,
  type PriorityServiceId,
  type ServiceEngagement,
  type ServiceEngagementProjection,
} from "../contracts/serviceEngagementProjection.ts";
import { containsSecretShapedValue, EXPORT_OMIT_KEYS } from "./exportClientSafeEngagement.ts";

const LIFECYCLE_SET = new Set<string>(LIFECYCLE_STATES);
const EVIDENCE_SET = new Set<string>(EVIDENCE_CLASSES);
const SERVICE_SET = new Set<string>(PRIORITY_SERVICE_IDS);
const ACCEPTED_INPUT_VERSIONS = new Set([
  SERVICE_ENGAGEMENT_PROJECTION_VERSION,
  SERVICE_DELIVERY_PLANE_REPORT_VERSION,
]);

const BACKEND_LIFECYCLE_ALIASES: Record<string, LifecycleState> = {
  intake_requested: "intake",
  intake_received: "intake",
  draft: "intake",
  data_quality_assessed: "eligible",
  analysis_in_progress: "analysis",
  internal_review: "draft_ready",
  blocked: "paused",
  canceled: "cancelled",
};

const PACKAGE_ALIASES: Record<string, PriorityServiceId> = {
  "client_product_validation_sprint": "product-validation-sprint",
  "client_unit_economics_diagnostic": "unit-economics-cac-roas-diagnostic",
  "client_launch_draft_pack": "launch-draft-pack",
  "client_managed_acquisition_diagnostic": "managed-acquisition-cro",
};

const LEAKAGE_KEY = /(cross_client|cross_workspace|other_client|foreign_workspace|internal_notes)/i;

export function normalizeEvidenceClass(value: unknown): EvidenceClass {
  const raw = String(value ?? "").trim().toLowerCase().replace(/-/g, "_");
  if (EVIDENCE_SET.has(raw)) return raw as EvidenceClass;
  if (raw === "assumed" || raw === "planning_assumption") return "assumption";
  if (raw === "public_observed") return "observed";
  if (raw === "fixture_demo" || raw === "fixture_only") return "fixture";
  if (raw === "manual") return "manual_import";
  if (raw === "sample_verified" || raw === "verified") return "manual_import";
  if (raw === "live" || raw === "live_readonly") return "unavailable";
  return "unavailable";
}

export function neverUpgradeEvidenceClass(from: EvidenceClass, claimed: unknown): EvidenceClass {
  const next = normalizeEvidenceClass(claimed);
  const rank: Record<EvidenceClass, number> = {
    unavailable: 0,
    fixture: 1,
    simulated: 1,
    assumption: 2,
    manual_import: 2,
    supplier_claimed: 3,
    derived: 4,
    supplier_documented: 5,
    observed: 6,
    live_validated: 7,
  };
  if (rank[next] > rank[from]) return from;
  return next;
}

export function normalizeLifecycle(value: unknown, dataInadequate: boolean): LifecycleState {
  const raw = String(value ?? "").trim().toLowerCase().replace(/-/g, "_");
  if (dataInadequate && (raw === "intake" || raw === "eligible" || raw === "screening" || raw === "data_quality_assessed" || raw === "")) {
    return "data_inadequate";
  }
  if (LIFECYCLE_SET.has(raw)) return raw as LifecycleState;
  if (raw in BACKEND_LIFECYCLE_ALIASES) {
    const mapped = BACKEND_LIFECYCLE_ALIASES[raw];
    if (dataInadequate && mapped === "eligible") return "data_inadequate";
    return mapped;
  }
  return "unavailable";
}

export function normalizeServiceId(value: unknown): PriorityServiceId | null {
  const raw = String(value ?? "").trim().toLowerCase();
  if (SERVICE_SET.has(raw)) return raw as PriorityServiceId;
  if (raw in PACKAGE_ALIASES) return PACKAGE_ALIASES[raw];
  if (raw.includes("product") && raw.includes("valid")) return "product-validation-sprint";
  if (raw.includes("unit") || raw.includes("cac") || raw.includes("roas")) {
    return "unit-economics-cac-roas-diagnostic";
  }
  if (raw.includes("launch") && raw.includes("draft")) return "launch-draft-pack";
  if (raw.includes("acquisition") || raw.includes("cro") || raw.includes("managed-marketing")) {
    return "managed-acquisition-cro";
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export type AdapterResult = {
  projection: ServiceEngagementProjection;
  rejected: boolean;
  rejection_reason: string | null;
};

export function adaptServiceProjection(raw: unknown, generatedAt = "fixture"): AdapterResult {
  const record = asRecord(raw);
  if (!record) {
    return unavailableResult("malformed_artifact: payload is not an object", generatedAt);
  }
  if (hasLeakageKeys(record) || containsSecretShapedValue(omitInternalOperatorFields(record))) {
    return unavailableResult("secret_or_cross_workspace_field_rejected", generatedAt);
  }

  if (record.status === "rate_limited") {
    return unavailableResult("service_delivery_projection_rate_limited", generatedAt);
  }
  if (record.engagements !== undefined && !Array.isArray(record.engagements)) {
    return unavailableResult("malformed_artifact: engagements must be an array", generatedAt);
  }
  if (record.packages !== undefined && !Array.isArray(record.packages)) {
    return unavailableResult("malformed_artifact: packages must be an array", generatedAt);
  }

  const version = String(record.schema_version ?? record.schemaVersion ?? record.report_version ?? "");
  const inputContract = version === SERVICE_DELIVERY_PLANE_REPORT_VERSION
    ? SERVICE_DELIVERY_PLANE_REPORT_VERSION
    : version === SERVICE_ENGAGEMENT_PROJECTION_VERSION || version === ""
      ? SERVICE_ENGAGEMENT_PROJECTION_VERSION
      : "unknown";
  if (version && !ACCEPTED_INPUT_VERSIONS.has(version)) {
    return unavailableResult(`unsupported schema_version ${version}`, generatedAt, inputContract);
  }

  const rows = collectRawEngagements(record);
  const liveEndpointStatus = record.live_endpoint_status === "available_read_only"
    ? "available_read_only" as const
    : "unavailable" as const;
  const availability = record.availability === "unavailable"
    ? "unavailable"
    : record.availability === "manual_import"
      ? "manual_import"
      : record.availability === "partial"
        ? "partial"
        : version === SERVICE_DELIVERY_PLANE_REPORT_VERSION
          ? "manual_import"
          : "fixture";
  const engagements: ServiceEngagement[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const adapted = adaptEngagement(row, availability);
    if (!adapted.ok) {
      return unavailableResult(adapted.reason, generatedAt, inputContract);
    }
    if (seen.has(adapted.engagement.engagement_id)) {
      return unavailableResult(`duplicate_engagement_id ${adapted.engagement.engagement_id}`, generatedAt, inputContract);
    }
    seen.add(adapted.engagement.engagement_id);
    engagements.push(adapted.engagement);
  }

  return {
    rejected: false,
    rejection_reason: null,
    projection: {
      schema_version: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
      availability,
      live_endpoint: FUTURE_WORKBENCH_PATH,
      live_endpoint_status: liveEndpointStatus,
      read_only: true,
      generated_at: String(record.generated_at ?? generatedAt),
      engagements,
      input_contract: inputContract,
      diagnostics: [
        ...((Array.isArray(record.diagnostics) ? record.diagnostics : []).map((item) => String(item))),
        liveEndpointStatus === "available_read_only"
          ? "GET /api/service-delivery/workbench is available read-only; this adapter never ranks or recalculates economics."
          : "GET /api/service-delivery/workbench is unavailable; this adapter never ranks or recalculates economics.",
      ],
    },
  };
}

function collectRawEngagements(record: Record<string, unknown>): unknown[] {
  if (Array.isArray(record.engagements)) return record.engagements;
  if (Array.isArray(record.client_engagements)) return record.client_engagements;
  if (Array.isArray(record.packages)) {
    const nested = record.packages.filter((item) => Boolean(asRecord(item)?.engagement_id));
    if (nested.length) return nested;
  }
  return [];
}

function unavailableResult(
  reason: string,
  generatedAt: string,
  inputContract: ServiceEngagementProjection["input_contract"] = "unknown",
): AdapterResult {
  return {
    rejected: true,
    rejection_reason: reason,
    projection: {
      schema_version: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
      availability: "unavailable",
      live_endpoint: FUTURE_WORKBENCH_PATH,
      live_endpoint_status: "unavailable",
      read_only: true,
      generated_at: generatedAt,
      engagements: [],
      input_contract: inputContract,
      diagnostics: [reason],
    },
  };
}

function omitInternalOperatorFields(value: unknown): unknown {
  const omit = new Set<string>(EXPORT_OMIT_KEYS);
  if (Array.isArray(value)) return value.map(omitInternalOperatorFields);
  const record = asRecord(value);
  if (!record) return value;
  const next: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(record)) {
    if (omit.has(key)) continue;
    next[key] = omitInternalOperatorFields(item);
  }
  return next;
}

function hasLeakageKeys(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some(hasLeakageKeys);
  return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
    if (LEAKAGE_KEY.test(key)) return true;
    return hasLeakageKeys(item);
  });
}

type AdaptEngagementResult =
  | { ok: true; engagement: ServiceEngagement }
  | { ok: false; reason: string };

function demoteLiveValidated(
  value: EvidenceClass,
  availability: ServiceEngagementProjection["availability"],
  base: EvidenceClass,
): EvidenceClass {
  if (value !== "live_validated") return value;
  if (
    availability === "fixture"
    || availability === "manual_import"
    || availability === "partial"
    || availability === "unavailable"
    || base === "fixture"
    || base === "manual_import"
    || base === "simulated"
    || base === "assumption"
  ) {
    if (base === "simulated") return "simulated";
    if (availability === "fixture" || base === "fixture") return "fixture";
    return "manual_import";
  }
  return value;
}

function adaptEngagement(
  raw: unknown,
  availability: ServiceEngagementProjection["availability"] = "fixture",
): AdaptEngagementResult {
  const record = asRecord(raw);
  if (!record) return { ok: false, reason: "malformed_artifact: engagement is not an object" };
  if (hasLeakageKeys(record)) {
    return { ok: false, reason: "cross_workspace_field_rejected" };
  }
  const engagementId = String(record.engagement_id ?? "").trim();
  if (!engagementId) return { ok: false, reason: "missing_engagement_id" };
  const serviceId = normalizeServiceId(record.service_id ?? record.package_id);
  if (!serviceId) return { ok: false, reason: `unknown_package_id ${String(record.package_id ?? record.service_id)}` };

  const eligibility = asRecord(record.eligibility) ?? {};
  const dataInadequate = Boolean(
    eligibility.data_inadequate
    || record.data_quality_state === "data_inadequate"
    || record.lifecycle_state === "data_inadequate",
  );
  const intake = asRecord(record.intake) ?? {};
  const intakeData = asRecord(record.intake_data);
  const economics = asRecord(record.economics) ?? {};
  const capacity = asRecord(record.capacity) ?? {};
  const nba = asRecord(record.next_best_action);
  const nbaAction = nba
    ? String(nba.action ?? "")
    : typeof record.next_best_action === "string"
      ? record.next_best_action
      : "";
  const financial = asRecord(record.financial_readiness) ?? {};
  const evidenceSource = Array.isArray(record.evidence)
    ? record.evidence
    : Array.isArray(record.evidence_set)
      ? record.evidence_set
      : [];
  const missing = toStringList(record.missing_data).length
    ? toStringList(record.missing_data)
    : toStringList(record.missing_information);

  return {
    ok: true,
    engagement: {
      engagement_id: engagementId,
      service_id: serviceId,
      lifecycle_state: normalizeLifecycle(record.lifecycle_state ?? record.lifecycle, dataInadequate),
      intake: {
        client_id: String(intake.client_id ?? record.client_id ?? "unknown-client"),
        display_name: String(intake.display_name ?? record.client_name ?? record.client_id ?? "Unnamed client"),
        workspace_id: String(intake.workspace_id ?? record.workspace_id ?? "unknown-workspace"),
        contact_channel: String(intake.contact_channel ?? "not_collected"),
        fields: mapIntakeFields(intake, intakeData),
      },
      eligibility: {
        eligible: Boolean(eligibility.eligible) && !dataInadequate,
        data_inadequate: dataInadequate,
        reasons: toStringList(eligibility.reasons).length
          ? toStringList(eligibility.reasons)
          : (dataInadequate ? missing : []),
        required_from_client: Array.isArray(eligibility.required_from_client)
          ? eligibility.required_from_client.map((item) => {
            const row = asRecord(item) ?? {};
            return {
              field: String(row.field ?? "unspecified"),
              why: String(row.why ?? "Required before analysis can proceed."),
              how_to_provide: String(row.how_to_provide ?? "Upload a client-safe export of the source record."),
            };
          })
          : missing.map((field) => ({
            field,
            why: "Listed as missing_information on the #261 engagement copy.",
            how_to_provide: `Provide ${field} as a client-safe record.`,
          })),
      },
      evidence: evidenceSource.map((item, index) => {
        const row = asRecord(item) ?? {};
        const base = normalizeEvidenceClass(row.base_class ?? row.evidence_class ?? row.class);
        const claimed = neverUpgradeEvidenceClass(base, row.evidence_class ?? row.class);
        return {
          evidence_id: String(row.evidence_id ?? row.reference_id ?? `ev-${index}`),
          title: String(row.title ?? row.label ?? "Evidence item"),
          evidence_class: demoteLiveValidated(claimed, availability, base),
          summary: String(row.summary ?? row.note ?? documentRef(row)),
          collected_at: row.collected_at == null
            ? (row.captured_at == null ? null : String(row.captured_at))
            : String(row.collected_at),
        };
      }),
      financial_readiness: {
        ready: Boolean(financial.ready) && !dataInadequate,
        missing: toStringList(financial.missing).length ? toStringList(financial.missing) : missing,
        note: String(financial.note ?? "Financial figures are display copies only. The frontend does not calculate contribution."),
      },
      deliverables: mapDeliverables(record, dataInadequate),
      economics: {
        authority: "backend_service_economics",
        frontend_calculates: false,
        fee: displayMoney(economics.fee ?? record.fee),
        contribution: displayMoney(economics.contribution ?? record.contribution),
        contribution_unavailable_reason: (economics.contribution ?? record.contribution)
          ? null
          : String(economics.contribution_unavailable_reason ?? "No sanitized contribution copy was supplied."),
        planning_assumption_note: String(
          economics.planning_assumption_note
          ?? "Price, CAC, ROAS, and contribution labels are planning assumptions unless marked live_validated by the backend.",
        ),
      },
      capacity: {
        state: (["ok", "warning", "blocked", "unavailable"].includes(String(capacity.state))
          ? String(capacity.state)
          : "unavailable") as ServiceEngagement["capacity"]["state"],
        message: String(capacity.message ?? "Capacity signal unavailable."),
        concurrent_label: capacity.concurrent_label == null ? null : String(capacity.concurrent_label),
      },
      assumptions: toStringList(record.assumptions).length
        ? toStringList(record.assumptions)
        : (record.scope ? [String(record.scope)] : []),
      missing_data: missing,
      next_best_action: {
        action: nbaAction || (dataInadequate
          ? "Collect the missing client records listed on this engagement."
          : "Review intake and wait for a canonical workbench projection."),
        owner: (["operator", "client", "blocked"].includes(String(nba?.owner ?? ""))
          ? String(nba?.owner)
          : dataInadequate ? "client" : "blocked") as "operator" | "client" | "blocked",
        executes_live_action: false,
        rationale: String(nba?.rationale ?? "This workbench is read-only and does not execute CompanyOS transitions."),
      },
      creative_assets: Array.isArray(record.creative_assets)
        ? record.creative_assets.map((item) => {
          const row = asRecord(item) ?? {};
          const skill = String(row.skill_id);
          const allowed = ["product-photoshoot", "marketplace-cards", "brandkit", "video-explainer"] as const;
          const skill_id = (allowed as readonly string[]).includes(skill)
            ? skill as typeof allowed[number]
            : "product-photoshoot";
          return {
            skill_id,
            title: String(row.title ?? skill_id),
            status: "unavailable" as const,
            generation_enabled: false as const,
            publication_enabled: false as const,
            note: String(row.note ?? "Higgsfield remains draft/unavailable metadata only."),
          };
        })
        : [],
      private_operator_notes: record.private_operator_notes == null ? null : String(record.private_operator_notes),
      internal_prompt: record.internal_prompt == null ? null : String(record.internal_prompt),
      internal_formula: record.internal_formula == null ? null : String(record.internal_formula),
      updated_at: String(record.updated_at ?? "offline-fixture"),
      stale: Boolean(record.stale) || (Array.isArray(record.stale_fields) && record.stale_fields.length > 0),
      renewal_state: record.renewal_state == null ? null : String(record.renewal_state),
      approval_state: record.approval_state == null ? null : String(record.approval_state),
      delivery_state: record.delivery_state == null ? null : String(record.delivery_state),
    },
  };
}

function mapIntakeFields(
  intake: Record<string, unknown>,
  intakeData: Record<string, unknown> | null,
): ServiceEngagement["intake"]["fields"] {
  if (Array.isArray(intake.fields)) {
    return intake.fields.map((field, index) => {
      const item = asRecord(field) ?? {};
      return {
        field_id: String(item.field_id ?? `field-${index}`),
        label: String(item.label ?? item.field_id ?? "Field"),
        status: (["received", "missing", "stale", "conflicting"].includes(String(item.status))
          ? String(item.status)
          : "missing") as "received" | "missing" | "stale" | "conflicting",
        client_must_provide: String(item.client_must_provide ?? "Provide the missing client record."),
      };
    });
  }
  if (!intakeData) return [];
  return Object.entries(intakeData).map(([key, value], index) => ({
    field_id: `intake-${index}`,
    label: key,
    status: value == null || value === "" ? "missing" as const : "received" as const,
    client_must_provide: value == null || value === "" ? `Provide ${key}.` : `${key} already recorded as a display copy.`,
  }));
}

function mapDeliverables(record: Record<string, unknown>, dataInadequate: boolean): ServiceEngagement["deliverables"] {
  if (Array.isArray(record.deliverables)) {
    return record.deliverables.map((item, index) => {
      const row = asRecord(item) ?? {};
      return {
        deliverable_id: String(row.deliverable_id ?? `del-${index}`),
        name: String(row.name ?? "Deliverable"),
        status: (["not_started", "in_progress", "blocked", "draft_ready", "client_safe", "rejected"]
          .includes(String(row.status))
          ? String(row.status)
          : dataInadequate ? "blocked" : "not_started") as ServiceEngagement["deliverables"][number]["status"],
        blocked_reason: row.blocked_reason == null ? null : String(row.blocked_reason),
      };
    });
  }
  const ids = toStringList(record.deliverable_ids);
  return ids.map((id, index) => ({
    deliverable_id: id || `del-${index}`,
    name: id || "Deliverable",
    status: dataInadequate ? "blocked" as const : "not_started" as const,
    blocked_reason: dataInadequate ? "Blocked while the engagement is data_inadequate." : null,
  }));
}

function documentRef(row: Record<string, unknown>): string {
  return String(row.document_ref ?? row.note ?? "");
}

function displayMoney(raw: unknown): ServiceEngagement["economics"]["fee"] {
  const record = asRecord(raw);
  if (!record) return null;
  const amount = record.amount_label ?? record.amount ?? record.value;
  if (amount == null) return null;
  return {
    amount_label: String(amount),
    currency: String(record.currency ?? "USD"),
    evidence_class: normalizeEvidenceClass(record.evidence_class ?? record.evidence_state),
    source: "backend_service_economics",
    display_only: true,
  };
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}
