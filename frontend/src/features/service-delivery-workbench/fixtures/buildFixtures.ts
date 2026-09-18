import {
  LIFECYCLE_STATES,
  PRIORITY_SERVICE_IDS,
  SERVICE_ENGAGEMENT_PROJECTION_VERSION,
  type CreativeAssetRequest,
  type EvidenceClass,
  type EvidenceItem,
  type LifecycleState,
  type PriorityServiceId,
  type ServiceEngagement,
  type ServiceEngagementProjection,
} from "../contracts/serviceEngagementProjection.ts";
import { HIGGSFIELD_DRAFT_SKILLS } from "../lib/creativeAssetContract.ts";

const EVIDENCE_CYCLE: EvidenceClass[] = [
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
];

function creativeDraft(title: string): CreativeAssetRequest[] {
  return HIGGSFIELD_DRAFT_SKILLS.map((skill) => ({
    skill_id: skill.skill_id,
    title: `${title} / ${skill.skill_id}`,
    status: "unavailable",
    generation_enabled: false,
    publication_enabled: false,
    note: skill.note,
  }));
}

export function requiredInputsFor(serviceId: PriorityServiceId): { field: string; why: string; how_to_provide: string }[] {
  const common = [
    {
      field: "client identity and workspace",
      why: "Engagements are tenant-scoped and cannot be mixed across clients.",
      how_to_provide: "Confirm the legal client name and the assigned client_service workspace id.",
    },
  ];
  if (serviceId === "product-validation-sprint") {
    return [
      ...common,
      {
        field: "named product candidate",
        why: "The sprint reviews one candidate; a category-only brief is data_inadequate.",
        how_to_provide: "Send SKU or exact product title, target marketplace, and any supplier URL the client already has.",
      },
      {
        field: "marketplace / supplier / consumer evidence or permission to collect it",
        why: "Without those three evidence families the sprint cannot issue a go/hold/no-go.",
        how_to_provide: "Upload client-safe marketplace screenshots, supplier quotes, and consumer-review exports, or approve offline collection.",
      },
    ];
  }
  if (serviceId === "unit-economics-cac-roas-diagnostic") {
    return [
      ...common,
      {
        field: "priced product or campaign",
        why: "Unit economics cannot be diagnosed without a price and a cost or spend record.",
        how_to_provide: "Provide COGS, selling price, shipping, and 30+ days of order or ad-spend history if it exists.",
      },
      {
        field: "attribution method in use",
        why: "CAC/ROAS labels are meaningless if the client’s attribution window is unknown.",
        how_to_provide: "State platform-reported, blended, or last-click and the date range.",
      },
    ];
  }
  if (serviceId === "launch-draft-pack") {
    return [
      ...common,
      {
        field: "product-validation or equivalent evidence pack",
        why: "Launch drafts must not invent demand, supplier, or claim evidence.",
        how_to_provide: "Attach the Product Validation Sprint packet or an equivalent client-safe evidence export.",
      },
      {
        field: "brand constraints and prohibited claims",
        why: "Draft copy cannot include medical, guaranteed-profit, or unapproved claims.",
        how_to_provide: "List brand name, language, currency, and claims the client forbids.",
      },
    ];
  }
  return [
    ...common,
    {
      field: "approved creative tests and measurement plan",
      why: "Managed acquisition/CRO is ineligible without a test plan and a budget cap policy.",
      how_to_provide: "Provide the current funnel URL (draft), KPI definitions, and a human-approved budget ceiling as a planning number.",
    },
    {
      field: "consent and claims policy",
      why: "The retainer cannot recommend live campaign changes or messages.",
      how_to_provide: "Confirm that no live campaign mutation is requested and share the claims/consent policy.",
    },
  ];
}

function evidenceFor(
  engagementId: string,
  serviceId: PriorityServiceId,
  lifecycle: LifecycleState,
  count: number,
): EvidenceItem[] {
  const items: EvidenceItem[] = [];
  for (let index = 0; index < count; index += 1) {
    const evidence_class = EVIDENCE_CYCLE[index % EVIDENCE_CYCLE.length];
    items.push({
      evidence_id: `${engagementId}-ev-${index + 1}`,
      title: `${serviceId} evidence ${index + 1}`,
      evidence_class,
      summary: lifecycle === "data_inadequate"
        ? "Placeholder only. Client has not supplied the source record."
        : `Sanitized ${evidence_class} record. Class is never upgraded in the UI.`,
      collected_at: evidence_class === "unavailable" ? null : `2026-09-0${(index % 8) + 1}`,
    });
  }
  return items;
}

export function buildEngagement(options: {
  index: number;
  clientName: string;
  clientId: string;
  serviceId: PriorityServiceId;
  lifecycle: LifecycleState;
  dataInadequate?: boolean;
  evidenceCount?: number;
  deliverableCount?: number;
  includeInternal?: boolean;
  stale?: boolean;
  capacity?: ServiceEngagement["capacity"]["state"];
}): ServiceEngagement {
  const engagement_id = `eng-${String(options.index).padStart(4, "0")}`;
  const dataInadequate = Boolean(options.dataInadequate || options.lifecycle === "data_inadequate");
  const required = requiredInputsFor(options.serviceId);
  const feeLabel = options.serviceId === "managed-acquisition-cro" ? "2500.00" : "1200.00";
  return {
    engagement_id,
    service_id: options.serviceId,
    lifecycle_state: options.lifecycle,
    intake: {
      client_id: options.clientId,
      display_name: options.clientName,
      workspace_id: `ws-${options.clientId}`,
      contact_channel: "operator_recorded",
      fields: required.map((item, fieldIndex) => ({
        field_id: `${engagement_id}-in-${fieldIndex + 1}`,
        label: item.field,
        status: dataInadequate && fieldIndex > 0 ? "missing" : "received",
        client_must_provide: item.how_to_provide,
      })),
    },
    eligibility: {
      eligible: !dataInadequate && !["rejected", "cancelled", "unavailable"].includes(options.lifecycle),
      data_inadequate: dataInadequate,
      reasons: dataInadequate
        ? required.slice(1).map((item) => item.why)
        : [`${options.clientName} matches ${options.serviceId} eligibility copy.`],
      required_from_client: dataInadequate ? required.slice(1) : [],
    },
    evidence: evidenceFor(
      engagement_id,
      options.serviceId,
      options.lifecycle,
      options.evidenceCount ?? (dataInadequate ? 3 : 8),
    ),
    financial_readiness: {
      ready: !dataInadequate && ["analysis", "draft_ready", "client_review", "approved", "delivered"].includes(options.lifecycle),
      missing: dataInadequate ? required.slice(1).map((item) => item.field) : [],
      note: "This panel does not compute CAC, ROAS, contribution, or fees. It only shows sanitized copies.",
    },
    deliverables: Array.from({ length: options.deliverableCount ?? 4 }, (_, index) => ({
      deliverable_id: `${engagement_id}-d-${index + 1}`,
      name: `${options.serviceId} deliverable ${index + 1}`,
      status: dataInadequate
        ? "blocked"
        : index === 0
          ? "draft_ready"
          : index === 1
            ? "in_progress"
            : "not_started",
      blocked_reason: dataInadequate
        ? `Blocked until the client provides: ${required[1]?.field ?? "missing intake"}.`
        : null,
    })),
    economics: {
      authority: "backend_service_economics",
      frontend_calculates: false,
      fee: dataInadequate
        ? null
        : {
          amount_label: feeLabel,
          currency: "USD",
          evidence_class: "assumption",
          source: "backend_service_economics",
          display_only: true,
        },
      contribution: ["approved", "delivered"].includes(options.lifecycle)
        ? {
          amount_label: "410.00",
          currency: "USD",
          evidence_class: "assumption",
          source: "backend_service_economics",
          display_only: true,
        }
        : null,
      contribution_unavailable_reason: ["approved", "delivered"].includes(options.lifecycle)
        ? null
        : "No sanitized contribution copy was supplied; the UI will not invent one.",
      planning_assumption_note:
        "Fee and contribution labels are backend copies. Planning thresholds are not commercial validation.",
    },
    capacity: {
      state: options.capacity ?? (options.index % 17 === 0 ? "warning" : "ok"),
      message: options.capacity === "warning" || options.index % 17 === 0
        ? "Capacity warning: too many concurrent analysis-stage engagements for one operator lane. Queue, do not start live work."
        : "Capacity signal is a planning label, not a staffing system.",
      concurrent_label: options.index % 17 === 0 ? "8 concurrent / planning cap 6" : "3 concurrent / planning cap 6",
    },
    assumptions: [
      "Price bands are catalog planning assumptions.",
      "No live client account, message, charge, or campaign mutation is authorized.",
    ],
    missing_data: dataInadequate ? required.slice(1).map((item) => item.field) : [],
    next_best_action: {
      action: dataInadequate
        ? `Ask ${options.clientName} to provide: ${required[1]?.field ?? "missing intake fields"}.`
        : options.lifecycle === "draft_ready"
          ? "Open the client-safe export preview; do not publish."
          : "Continue the read-only checklist for the current lifecycle state.",
      owner: dataInadequate ? "client" : "operator",
      executes_live_action: false,
      rationale: "Workbench actions are operator review steps only.",
    },
    creative_assets: creativeDraft(options.clientName),
    private_operator_notes: options.includeInternal ? "INTERNAL: margin heuristic 0.62, do not export." : null,
    internal_prompt: options.includeInternal ? "SYSTEM PROMPT: score clients for upsell" : null,
    internal_formula: options.includeInternal ? "contribution = fee - labor - tooling" : null,
    updated_at: "2026-09-18T00:00:00Z",
    stale: Boolean(options.stale),
  };
}

const CLIENT_NAMES = [
  "Northwind Goods",
  "Harbor Peak Supply",
  "Cedar & Co. Retail",
  "Lumen Pet Studio",
  "Atlas Home Lab",
  "Mesa Outdoor Co",
  "Quilted Market",
  "Solstice Beauty Co",
  "Pine & Parcel",
  "Ironleaf Tools",
];

export function buildOneClientProjection(): ServiceEngagementProjection {
  return {
    schema_version: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
    availability: "fixture",
    live_endpoint: "/api/service-delivery/workbench",
    live_endpoint_status: "unavailable",
    read_only: true,
    generated_at: "2026-09-18T00:00:00Z",
    input_contract: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
    diagnostics: ["Canonical live endpoint unavailable; one-client fixture in use."],
    engagements: [
      buildEngagement({
        index: 1,
        clientName: CLIENT_NAMES[0],
        clientId: "client-northwind",
        serviceId: "product-validation-sprint",
        lifecycle: "data_inadequate",
        dataInadequate: true,
      }),
    ],
  };
}

export function buildTenClientProjection(): ServiceEngagementProjection {
  const engagements = CLIENT_NAMES.map((name, index) => buildEngagement({
    index: index + 1,
    clientName: name,
    clientId: `client-${index + 1}`,
    serviceId: PRIORITY_SERVICE_IDS[index % PRIORITY_SERVICE_IDS.length],
    lifecycle: LIFECYCLE_STATES[index % LIFECYCLE_STATES.length],
    dataInadequate: LIFECYCLE_STATES[index % LIFECYCLE_STATES.length] === "data_inadequate",
    stale: index === 8,
    includeInternal: index === 3,
    capacity: index === 6 ? "warning" : "ok",
  }));
  return {
    schema_version: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
    availability: "partial",
    live_endpoint: "/api/service-delivery/workbench",
    live_endpoint_status: "unavailable",
    read_only: true,
    generated_at: "2026-09-18T00:00:00Z",
    input_contract: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
    diagnostics: ["Ten-client fixture covers every priority service and mixed lifecycle states."],
    engagements,
  };
}

export function buildScaleProjection(count = 100, evidenceCount = 24, deliverableCount = 12): ServiceEngagementProjection {
  const engagements = Array.from({ length: count }, (_, index) => buildEngagement({
    index: index + 1,
    clientName: `${CLIENT_NAMES[index % CLIENT_NAMES.length]} ${Math.floor(index / 10) + 1}`,
    clientId: `client-scale-${index + 1}`,
    serviceId: PRIORITY_SERVICE_IDS[index % PRIORITY_SERVICE_IDS.length],
    lifecycle: LIFECYCLE_STATES[index % LIFECYCLE_STATES.length],
    dataInadequate: LIFECYCLE_STATES[index % LIFECYCLE_STATES.length] === "data_inadequate",
    evidenceCount,
    deliverableCount,
  }));
  return {
    schema_version: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
    availability: "fixture",
    live_endpoint: "/api/service-delivery/workbench",
    live_endpoint_status: "unavailable",
    read_only: true,
    generated_at: "2026-09-18T00:00:00Z",
    input_contract: SERVICE_ENGAGEMENT_PROJECTION_VERSION,
    diagnostics: [`Scale fixture: ${count} engagements, ${evidenceCount} evidence rows, ${deliverableCount} deliverables.`],
    engagements,
  };
}

export function buildDemoProjection(): ServiceEngagementProjection {
  const ten = buildTenClientProjection();
  const extra = [
    buildEngagement({
      index: 21,
      clientName: "Northwind Goods",
      clientId: "client-1",
      serviceId: "launch-draft-pack",
      lifecycle: "draft_ready",
    }),
    buildEngagement({
      index: 22,
      clientName: "Harbor Peak Supply",
      clientId: "client-2",
      serviceId: "unit-economics-cac-roas-diagnostic",
      lifecycle: "analysis",
    }),
    buildEngagement({
      index: 23,
      clientName: "Lumen Pet Studio",
      clientId: "client-4",
      serviceId: "managed-acquisition-cro",
      lifecycle: "paused",
      capacity: "warning",
    }),
  ];
  return { ...ten, engagements: [...ten.engagements, ...extra] };
}
