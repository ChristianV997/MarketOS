export const CONSULTING_RESEARCH_REVIEW_VERSION = "consulting-research-review-v1";

export const EVIDENCE_CLASSES = [
  "observed",
  "manual",
  "fixture",
  "derived",
  "assumed",
  "unavailable",
] as const;

export type EvidenceClass = (typeof EVIDENCE_CLASSES)[number];

export const SECTION_IDS = [
  "demand",
  "customer",
  "competitor",
  "supplier",
  "logistics",
  "economics",
] as const;

export type SectionId = (typeof SECTION_IDS)[number];

export const OFFERING_KINDS = [
  "product_validation",
  "market_scan",
  "supplier_feasibility",
  "unit_economics",
  "unavailable",
] as const;

export type OfferingKind = (typeof OFFERING_KINDS)[number];

export interface EvidenceItem {
  evidence_id: string;
  title: string;
  evidence_class: EvidenceClass;
  summary: string;
  source_label: string | null;
  captured_at: string | null;
  fresh: boolean | null;
  conflict_note: string | null;
}

export interface ResearchSection {
  section_id: SectionId;
  question: string;
  items: EvidenceItem[];
  missing: string[];
}

export interface TimelineEvent {
  event_id: string;
  label: string;
  at: string | null;
  evidence_class: EvidenceClass;
}

export interface ConsultingResearchReview {
  review_version: typeof CONSULTING_RESEARCH_REVIEW_VERSION;
  engagement_id: string;
  display_name: string;
  offering_kind: OfferingKind;
  research_question: string;
  scope: string;
  sections: ResearchSection[];
  confidence_label: string | null;
  limitations: string[];
  blockers: string[];
  next_action: string;
  next_action_executes: false;
  timeline: TimelineEvent[];
  availability: "fixture" | "manual" | "partial" | "unavailable";
}

export const EXPORT_OMIT_LABELS = [
  "internal_prompt",
  "internal_formula",
  "source_code",
  "credentials",
  "raw_provider_payload",
  "hidden_heuristics",
  "cross_client_data",
] as const;
