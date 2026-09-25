import {
  EVIDENCE_CLASSES,
  RESEARCH_SURFACE_VERSION,
  SECTION_IDS,
  type EvidenceClass,
  type EvidenceRow,
  type ResearchSection,
  type ResearchSurfaceModel,
  type SectionId,
} from "../contracts/researchSurface.ts";

const CLASS_SET = new Set<string>(EVIDENCE_CLASSES);
const SECTION_SET = new Set<string>(SECTION_IDS);
const LEAK = /(cross[ _-]?client|cross[ _-]?workspace|another[ _-]?client|other[ _-]?client|different[ _-]?client|competing[ _-]?client|internal[ _-]?prompt|internal[ _-]?formula|raw[ _-]?payload|api[ _-]?key|heuristic[ _-]?weight)/i;
const SECRET = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;

export interface AdaptResult {
  rejected: boolean;
  reason: string | null;
  model: ResearchSurfaceModel;
}

function record(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function leaky(value: unknown): boolean {
  if (typeof value === "string") return SECRET.test(value) || LEAK.test(value);
  if (Array.isArray(value)) return value.some(leaky);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value as Record<string, unknown>).some(([key, item]) => LEAK.test(key) || leaky(item));
}

export function normalizeClass(value: unknown): EvidenceClass {
  const raw = String(value ?? "").trim().toLowerCase().replace(/-/g, "_");
  if (raw === "live" || raw === "live_validated" || raw === "live_readonly" || raw === "success") return "unavailable";
  if (raw === "manual_import") return "manual";
  if (raw === "fixture_only" || raw === "fixture_demo") return "fixture";
  if (raw === "assumption") return "assumed";
  if (CLASS_SET.has(raw)) return raw as EvidenceClass;
  return "unavailable";
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function row(raw: unknown, index: number): EvidenceRow | null {
  const item = record(raw);
  if (!item) return null;
  return {
    evidence_id: String(item.evidence_id ?? `row-${index}`),
    title: String(item.title ?? "Untitled"),
    evidence_class: normalizeClass(item.evidence_class),
    summary: String(item.summary ?? ""),
    source_label: item.source_label == null || String(item.source_label).trim() === "" ? null : String(item.source_label),
    captured_at: item.captured_at == null || String(item.captured_at).trim() === "" ? null : String(item.captured_at),
    fresh: typeof item.fresh === "boolean" ? item.fresh : null,
    conflict_note: item.conflict_note == null || String(item.conflict_note).trim() === "" ? null : String(item.conflict_note),
  };
}

function empty(reason: string): ResearchSurfaceModel {
  return {
    version: RESEARCH_SURFACE_VERSION,
    engagement_id: "unavailable",
    display_name: "Unavailable",
    offering_kind: "unavailable",
    sections: [],
    blockers: [reason],
    next_action: "Provide a consulting-research-surface-v1 packet. This surface does not invent evidence.",
    next_action_executes: false,
    availability: "unavailable",
    limitations: [reason],
    draft_only: true,
    live_validated: false,
    launch_authorized: false,
  };
}

export function adaptResearchSurface(raw: unknown): AdaptResult {
  const packet = record(raw);
  if (!packet) return { rejected: true, reason: "malformed", model: empty("Packet is not an object.") };
  if (leaky(packet)) return { rejected: true, reason: "prohibited_field", model: empty("Prohibited field rejected.") };
  if (String(packet.version ?? packet.review_version ?? "") !== RESEARCH_SURFACE_VERSION) {
    return { rejected: true, reason: "unsupported_version", model: empty("Unsupported surface version.") };
  }
  const engagementId = String(packet.engagement_id ?? "").trim();
  if (!engagementId) return { rejected: true, reason: "missing_engagement_id", model: empty("Missing engagement id.") };
  const sections: ResearchSection[] = [];
  const supplied = Array.isArray(packet.sections) ? packet.sections : [];
  for (const item of supplied) {
    const section = record(item);
    if (!section) continue;
    const id = String(section.section_id ?? "");
    if (!SECTION_SET.has(id)) continue;
    const rows = Array.isArray(section.rows) ? section.rows.map(row).filter((entry): entry is EvidenceRow => entry !== null) : [];
    sections.push({
      section_id: id as SectionId,
      title: String(section.title ?? id),
      rows,
      missing: strings(section.missing),
    });
  }
  const availabilityRaw = String(packet.availability ?? "unavailable");
  const availability = (["fixture", "manual", "partial", "unavailable"].includes(availabilityRaw)
    ? availabilityRaw
    : "unavailable") as ResearchSurfaceModel["availability"];
  return {
    rejected: false,
    reason: null,
    model: {
      version: RESEARCH_SURFACE_VERSION,
      engagement_id: engagementId,
      display_name: String(packet.display_name ?? engagementId),
      offering_kind: String(packet.offering_kind ?? "unavailable"),
      sections,
      blockers: strings(packet.blockers),
      next_action: String(packet.next_action ?? "Review missing evidence. This surface does not launch."),
      next_action_executes: false,
      availability,
      limitations: strings(packet.limitations),
      draft_only: true,
      live_validated: false,
      launch_authorized: false,
    },
  };
}
