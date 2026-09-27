export const RESEARCH_SURFACE_VERSION = "consulting-research-surface-v1";

export const EVIDENCE_CLASSES = ["observed", "manual", "fixture", "derived", "assumed", "unavailable"] as const;
export type EvidenceClass = (typeof EVIDENCE_CLASSES)[number];

export const SECTION_IDS = ["demand", "customer", "competitor", "supplier", "logistics", "economics"] as const;
export type SectionId = (typeof SECTION_IDS)[number];

export type SurfaceState = "loading" | "error" | "empty" | "unavailable" | "blocked" | "stale" | "partial";

export interface EvidenceRow {
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
  title: string;
  rows: EvidenceRow[];
  missing: string[];
}

export interface ResearchSurfaceModel {
  version: typeof RESEARCH_SURFACE_VERSION;
  engagement_id: string;
  display_name: string;
  offering_kind: string;
  sections: ResearchSection[];
  blockers: string[];
  next_action: string;
  next_action_executes: false;
  availability: "fixture" | "manual" | "partial" | "unavailable";
  limitations: string[];
  draft_only: true;
  live_validated: false;
  launch_authorized: false;
}

export const OMITTED_EXPORT_FIELDS = [
  "internal_prompt",
  "internal_formula",
  "source_code",
  "credentials",
  "raw_provider_payload",
  "hidden_heuristics",
  "cross_client_data",
] as const;
