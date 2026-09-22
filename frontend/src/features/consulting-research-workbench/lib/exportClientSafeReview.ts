import {
  EXPORT_OMIT_LABELS,
  type ConsultingResearchReview,
} from "../contracts/consultingResearchReview.ts";

const SECRET = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;
const FORBIDDEN = /prompt|formula|heuristic|source_code|private_key|credential|raw_payload|cross_client|cross_workspace/;

export function containsProhibitedValue(value: unknown): boolean {
  if (typeof value === "string") return SECRET.test(value);
  if (Array.isArray(value)) return value.some(containsProhibitedValue);
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
      if (FORBIDDEN.test(key.toLowerCase())) return true;
      return containsProhibitedValue(item);
    });
  }
  return false;
}

export interface ClientSafeReviewExport {
  accepted: boolean;
  reason: string | null;
  payload: Record<string, unknown> | null;
}

export function buildClientSafeReviewExport(review: ConsultingResearchReview): ClientSafeReviewExport {
  if (review.availability === "unavailable" || review.engagement_id === "unavailable") {
    return { accepted: false, reason: "unavailable_review", payload: null };
  }
  const payload = {
    engagement_id: review.engagement_id,
    display_name: review.display_name,
    offering_kind: review.offering_kind,
    research_question: review.research_question,
    scope: review.scope,
    availability: review.availability,
    live_validated: false,
    launch_authorized: false,
    confidence_label: review.confidence_label,
    limitations: review.limitations,
    blockers: review.blockers,
    next_action: review.next_action,
    next_action_executes: false,
    sections: review.sections.map((section) => ({
      section_id: section.section_id,
      question: section.question,
      missing: section.missing,
      items: section.items.map((item) => ({
        title: item.title,
        evidence_class: item.evidence_class,
        summary: item.summary,
        source_label: item.source_label,
        captured_at: item.captured_at,
        fresh: item.fresh,
        conflict_note: item.conflict_note,
      })),
    })),
    timeline: review.timeline.map((event) => ({
      label: event.label,
      at: event.at,
      evidence_class: event.evidence_class,
    })),
    omitted: [...EXPORT_OMIT_LABELS],
  };
  if (containsProhibitedValue(payload)) {
    return { accepted: false, reason: "prohibited_value", payload: null };
  }
  return { accepted: true, reason: null, payload };
}
