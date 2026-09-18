import {
  EVIDENCE_CLASSES,
  LIFECYCLE_STATES,
  PRIORITY_SERVICE_IDS,
  SERVICE_ENGAGEMENT_PROJECTION_VERSION,
  type EvidenceClass,
  type LifecycleState,
  type PriorityServiceId,
  type ServiceEngagement,
  type ServiceEngagementProjection,
} from "../contracts/serviceEngagementProjection.ts";

const LIFECYCLE_SET = new Set<string>(LIFECYCLE_STATES);
const EVIDENCE_SET = new Set<string>(EVIDENCE_CLASSES);
const SERVICE_SET = new Set<string>(PRIORITY_SERVICE_IDS);

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

export function normalizeEvidenceClass(value: unknown): EvidenceClass {
  const raw = String(value ?? "").trim().toLowerCase().replace(/-/g, "_");
  if (EVIDENCE_SET.has(raw)) return raw as EvidenceClass;
  if (raw === "assumed" || raw === "planning_assumption") return "assumption";
  if (raw === "public_observed") return "observed";
  if (raw === "fixture_demo" || raw === "fixture_only") return "fixture";
  if (raw === "manual") return "manual_import";
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
  if (dataInadequate && (raw === "intake" || raw === "eligible" || raw === "data_quality_assessed" || raw === "")) {
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
    return unavailableResult("payload is not an object", generatedAt);
  }
  const version = String(record.schema_version ?? record.schemaVersion ?? "");
  if (version && version !== SERVICE_ENGAGEMENT_PROJECTION_VERSION) {
    return unavailableResult(`unsupported schema_version ${version}`, generatedAt);
  }
  const rows = Array.isArray(record.engagements) ? record.engagements : [];
  const engagements: ServiceEngagement[] = [];
  const diagnostics: string[] = [];
  for (const row of rows) {
    const adapted = adaptEngagement(row);
    if (!adapted) {
      diagnostics.push("skipped engagement that is not a sanitized object");
      continue;
    }
    engagements.push(adapted);
  }
  return {
    rejected: false,
    rejection_reason: null,
    projection: {
      schema_version: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
      availability: record.availability === "partial" ? "partial" : "fixture",
      live_endpoint: "/api/service-delivery/workbench",
      live_endpoint_status: "unavailable",
      read_only: true,
      generated_at: String(record.generated_at ?? generatedAt),
      engagements,
      diagnostics: [
        ...diagnostics,
        ...((Array.isArray(record.diagnostics) ? record.diagnostics : [])
          .map((item) => String(item))),
      ],
    },
  };
}

function unavailableResult(reason: string, generatedAt: string): AdapterResult {
  return {
    rejected: true,
    rejection_reason: reason,
    projection: {
      schema_version: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
      availability: "unavailable",
      live_endpoint: "/api/service-delivery/workbench",
      live_endpoint_status: "unavailable",
      read_only: true,
      generated_at: generatedAt,
      engagements: [],
      diagnostics: [reason],
    },
  };
}

function adaptEngagement(raw: unknown): ServiceEngagement | null {
  const record = asRecord(raw);
  if (!record) return null;
  const serviceId = normalizeServiceId(record.service_id ?? record.package_id);
  if (!serviceId) return null;
  const eligibility = asRecord(record.eligibility) ?? {};
  const dataInadequate = Boolean(eligibility.data_inadequate);
  const intake = asRecord(record.intake) ?? {};
  const economics = asRecord(record.economics) ?? {};
  const capacity = asRecord(record.capacity) ?? {};
  const nba = asRecord(record.next_best_action) ?? {};
  const financial = asRecord(record.financial_readiness) ?? {};
  return {
    engagement_id: String(record.engagement_id ?? "unknown"),
    service_id: serviceId,
    lifecycle_state: normalizeLifecycle(record.lifecycle_state ?? record.lifecycle, dataInadequate),
    intake: {
      client_id: String(intake.client_id ?? record.client_id ?? "unknown-client"),
      display_name: String(intake.display_name ?? record.client_name ?? "Unnamed client"),
      workspace_id: String(intake.workspace_id ?? record.workspace_id ?? "unknown-workspace"),
      contact_channel: String(intake.contact_channel ?? "not_collected"),
      fields: Array.isArray(intake.fields)
        ? intake.fields.map((field, index) => {
          const item = asRecord(field) ?? {};
          return {
            field_id: String(item.field_id ?? `field-${index}`),
            label: String(item.label ?? item.field_id ?? "Field"),
            status: (["received", "missing", "stale", "conflicting"].includes(String(item.status))
              ? String(item.status)
              : "missing") as "received" | "missing" | "stale" | "conflicting",
            client_must_provide: String(item.client_must_provide ?? "Provide the missing client record."),
          };
        })
        : [],
    },
    eligibility: {
      eligible: Boolean(eligibility.eligible) && !dataInadequate,
      data_inadequate: dataInadequate,
      reasons: toStringList(eligibility.reasons),
      required_from_client: Array.isArray(eligibility.required_from_client)
        ? eligibility.required_from_client.map((item) => {
          const row = asRecord(item) ?? {};
          return {
            field: String(row.field ?? "unspecified"),
            why: String(row.why ?? "Required before analysis can proceed."),
            how_to_provide: String(row.how_to_provide ?? "Upload a client-safe export of the source record."),
          };
        })
        : [],
    },
    evidence: Array.isArray(record.evidence)
      ? record.evidence.map((item, index) => {
        const row = asRecord(item) ?? {};
        return {
          evidence_id: String(row.evidence_id ?? `ev-${index}`),
          title: String(row.title ?? "Evidence item"),
          evidence_class: neverUpgradeEvidenceClass(
            normalizeEvidenceClass(row.base_class ?? row.evidence_class),
            row.evidence_class,
          ),
          summary: String(row.summary ?? ""),
          collected_at: row.collected_at == null ? null : String(row.collected_at),
        };
      })
      : [],
    financial_readiness: {
      ready: Boolean(financial.ready) && !dataInadequate,
      missing: toStringList(financial.missing),
      note: String(financial.note ?? "Financial figures are display copies only."),
    },
    deliverables: Array.isArray(record.deliverables)
      ? record.deliverables.map((item, index) => {
        const row = asRecord(item) ?? {};
        return {
          deliverable_id: String(row.deliverable_id ?? `del-${index}`),
          name: String(row.name ?? "Deliverable"),
          status: (["not_started", "in_progress", "blocked", "draft_ready", "client_safe", "rejected"]
            .includes(String(row.status))
            ? String(row.status)
            : "not_started") as ServiceEngagement["deliverables"][number]["status"],
          blocked_reason: row.blocked_reason == null ? null : String(row.blocked_reason),
        };
      })
      : [],
    economics: {
      authority: "backend_service_economics",
      frontend_calculates: false,
      fee: displayMoney(economics.fee),
      contribution: displayMoney(economics.contribution),
      contribution_unavailable_reason: economics.contribution
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
    assumptions: toStringList(record.assumptions),
    missing_data: toStringList(record.missing_data),
    next_best_action: {
      action: String(nba.action ?? "Review intake and wait for a canonical projection."),
      owner: (["operator", "client", "blocked"].includes(String(nba.owner))
        ? String(nba.owner)
        : "blocked") as "operator" | "client" | "blocked",
      executes_live_action: false,
      rationale: String(nba.rationale ?? "This workbench is read-only."),
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
    updated_at: String(record.updated_at ?? generatedNow()),
    stale: Boolean(record.stale),
  };
}

function displayMoney(raw: unknown): ServiceEngagement["economics"]["fee"] {
  const record = asRecord(raw);
  if (!record) return null;
  return {
    amount_label: String(record.amount_label ?? record.amount ?? "—"),
    currency: String(record.currency ?? "USD"),
    evidence_class: normalizeEvidenceClass(record.evidence_class),
    source: record.source === "backend_service_economics" ? "backend_service_economics" : "unavailable",
    display_only: true,
  };
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function generatedNow(): string {
  return "offline-fixture";
}
