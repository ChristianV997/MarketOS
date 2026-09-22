import { OMITTED_EXPORT_FIELDS, type ResearchSurfaceModel } from "../contracts/researchSurface.ts";

const SECRET = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;
const FORBIDDEN_KEY = /prompt|formula|heuristic|source_code|credential|raw_payload|cross_client|cross_workspace/;

export function containsProhibited(value: unknown): boolean {
  if (typeof value === "string") return SECRET.test(value);
  if (Array.isArray(value)) return value.some(containsProhibited);
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).some(([key, item]) => FORBIDDEN_KEY.test(key.toLowerCase()) || containsProhibited(item));
  }
  return false;
}

export function buildClientSafeSurfaceExport(model: ResearchSurfaceModel): { accepted: boolean; reason: string | null; payload: Record<string, unknown> | null } {
  if (model.availability === "unavailable" || model.engagement_id === "unavailable") {
    return { accepted: false, reason: "unavailable", payload: null };
  }
  const payload = {
    engagement_id: model.engagement_id,
    display_name: model.display_name,
    offering_kind: model.offering_kind,
    availability: model.availability,
    live_validated: false,
    launch_authorized: false,
    blockers: model.blockers,
    next_action: model.next_action,
    next_action_executes: false,
    limitations: model.limitations,
    sections: model.sections.map((section) => ({
      section_id: section.section_id,
      title: section.title,
      missing: section.missing,
      rows: section.rows.map((row) => ({
        title: row.title,
        evidence_class: row.evidence_class,
        summary: row.summary,
        source_label: row.source_label,
        captured_at: row.captured_at,
        fresh: row.fresh,
        conflict_note: row.conflict_note,
      })),
    })),
    omitted: [...OMITTED_EXPORT_FIELDS],
  };
  if (containsProhibited(payload)) return { accepted: false, reason: "prohibited_value", payload: null };
  return { accepted: true, reason: null, payload };
}
