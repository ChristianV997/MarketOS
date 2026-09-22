import {
  CONSULTING_RESEARCH_REVIEW_VERSION,
  EVIDENCE_CLASSES,
  OFFERING_KINDS,
  SECTION_IDS,
  type ConsultingResearchReview,
  type EvidenceClass,
  type EvidenceItem,
  type OfferingKind,
  type ResearchSection,
  type SectionId,
  type TimelineEvent,
} from "../contracts/consultingResearchReview.ts";

const EVIDENCE_SET = new Set<string>(EVIDENCE_CLASSES);
const SECTION_SET = new Set<string>(SECTION_IDS);
const OFFERING_SET = new Set<string>(OFFERING_KINDS);
const LEAKAGE = /(cross_client|cross_workspace|internal_prompt|internal_formula|raw_payload|api_key|private_key|heuristic_weight)/i;
const SECRET = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;

export interface AdapterResult {
  rejected: boolean;
  rejection_reason: string | null;
  review: ConsultingResearchReview;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function hasLeakage(value: unknown): boolean {
  if (typeof value === "string") return SECRET.test(value);
  if (Array.isArray(value)) return value.some(hasLeakage);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
    if (LEAKAGE.test(key)) return true;
    return hasLeakage(item);
  });
}

export function normalizeEvidenceClass(value: unknown): EvidenceClass {
  const raw = String(value ?? "").trim().toLowerCase().replace(/-/g, "_");
  if (raw === "live" || raw === "live_validated" || raw === "live_readonly") return "unavailable";
  if (raw === "assumption" || raw === "planning_assumption") return "assumed";
  if (raw === "manual_import") return "manual";
  if (raw === "fixture_demo" || raw === "fixture_only") return "fixture";
  if (EVIDENCE_SET.has(raw)) return raw as EvidenceClass;
  return "unavailable";
}

function normalizeOffering(value: unknown): OfferingKind {
  const raw = String(value ?? "").trim().toLowerCase();
  if (OFFERING_SET.has(raw)) return raw as OfferingKind;
  return "unavailable";
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function adaptItem(raw: unknown, index: number): EvidenceItem | null {
  const row = asRecord(raw);
  if (!row) return null;
  return {
    evidence_id: String(row.evidence_id ?? `ev-${index}`),
    title: String(row.title ?? "Untitled evidence"),
    evidence_class: normalizeEvidenceClass(row.evidence_class ?? row.class),
    summary: String(row.summary ?? ""),
    source_label: row.source_label == null || String(row.source_label).trim() === ""
      ? null
      : String(row.source_label),
    captured_at: row.captured_at == null || String(row.captured_at).trim() === ""
      ? null
      : String(row.captured_at),
    fresh: typeof row.fresh === "boolean" ? row.fresh : null,
    conflict_note: row.conflict_note == null || String(row.conflict_note).trim() === ""
      ? null
      : String(row.conflict_note),
  };
}

function adaptSection(raw: unknown, fallbackId: SectionId): ResearchSection | null {
  const row = asRecord(raw);
  if (!row) return null;
  const sectionId = String(row.section_id ?? fallbackId);
  if (!SECTION_SET.has(sectionId)) return null;
  const items = Array.isArray(row.items)
    ? row.items.map(adaptItem).filter((item): item is EvidenceItem => item !== null)
    : [];
  return {
    section_id: sectionId as SectionId,
    question: String(row.question ?? ""),
    items,
    missing: stringList(row.missing),
  };
}

function emptyReview(reason: string): ConsultingResearchReview {
  return {
    review_version: CONSULTING_RESEARCH_REVIEW_VERSION,
    engagement_id: "unavailable",
    display_name: "Unavailable engagement",
    offering_kind: "unavailable",
    research_question: reason,
    scope: "unavailable",
    sections: [],
    confidence_label: null,
    limitations: [reason],
    blockers: [reason],
    next_action: "Supply a consulting-research-review-v1 packet. This surface does not invent findings.",
    next_action_executes: false,
    timeline: [],
    availability: "unavailable",
  };
}

export function adaptConsultingResearch(raw: unknown): AdapterResult {
  const record = asRecord(raw);
  if (!record) {
    return { rejected: true, rejection_reason: "malformed_packet", review: emptyReview("Packet is not an object.") };
  }
  if (hasLeakage(record)) {
    return { rejected: true, rejection_reason: "secret_or_cross_client_rejected", review: emptyReview("Packet contained a prohibited field.") };
  }
  const version = String(record.review_version ?? record.schema_version ?? "");
  if (version !== CONSULTING_RESEARCH_REVIEW_VERSION) {
    return { rejected: true, rejection_reason: "unsupported_version", review: emptyReview("Unsupported review version.") };
  }
  const engagementId = String(record.engagement_id ?? "").trim();
  if (!engagementId) {
    return { rejected: true, rejection_reason: "missing_engagement_id", review: emptyReview("Missing engagement id.") };
  }
  const supplied = Array.isArray(record.sections) ? record.sections : [];
  const sections: ResearchSection[] = [];
  for (let index = 0; index < supplied.length; index += 1) {
    const section = adaptSection(supplied[index], SECTION_IDS[Math.min(index, SECTION_IDS.length - 1)]);
    if (section) sections.push(section);
  }
  const timeline: TimelineEvent[] = Array.isArray(record.timeline)
    ? record.timeline.map((item, index) => {
      const row = asRecord(item) ?? {};
      return {
        event_id: String(row.event_id ?? `tl-${index}`),
        label: String(row.label ?? "Unlabeled event"),
        at: row.at == null || String(row.at).trim() === "" ? null : String(row.at),
        evidence_class: normalizeEvidenceClass(row.evidence_class),
      };
    })
    : [];
  const availabilityRaw = String(record.availability ?? "unavailable");
  const availability = (["fixture", "manual", "partial", "unavailable"].includes(availabilityRaw)
    ? availabilityRaw
    : "unavailable") as ConsultingResearchReview["availability"];
  const confidence = record.confidence_label == null || String(record.confidence_label).trim() === ""
    ? null
    : String(record.confidence_label);
  return {
    rejected: false,
    rejection_reason: null,
    review: {
      review_version: CONSULTING_RESEARCH_REVIEW_VERSION,
      engagement_id: engagementId,
      display_name: String(record.display_name ?? engagementId),
      offering_kind: normalizeOffering(record.offering_kind),
      research_question: String(record.research_question ?? ""),
      scope: String(record.scope ?? ""),
      sections,
      confidence_label: confidence,
      limitations: stringList(record.limitations),
      blockers: stringList(record.blockers),
      next_action: String(record.next_action ?? "Review missing evidence. This surface does not launch."),
      next_action_executes: false,
      timeline,
      availability,
    },
  };
}
