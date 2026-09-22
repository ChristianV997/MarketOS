import { RESEARCH_SURFACE_VERSION, SECTION_IDS } from "../contracts/researchSurface.ts";

export function buildSurfaceFixture() {
  return {
    version: RESEARCH_SURFACE_VERSION,
    engagement_id: "surface-fixture-alpha",
    display_name: "Fixture research engagement",
    offering_kind: "market_scan",
    availability: "fixture",
    blockers: ["Supplier legal name is missing."],
    limitations: ["Fixture copy is not live validation."],
    next_action: "Collect the missing supplier record. Do not launch.",
    sections: SECTION_IDS.map((sectionId) => ({
      section_id: sectionId,
      title: sectionId,
      missing: sectionId === "supplier" ? ["supplier_legal_name"] : [],
      rows: [{
        evidence_id: `${sectionId}-1`,
        title: `${sectionId} note`,
        evidence_class: sectionId === "economics" ? "assumed" : "fixture",
        summary: "Supplied fixture copy.",
        source_label: "fixture-packet",
        captured_at: null,
        fresh: sectionId === "competitor" ? false : null,
        conflict_note: sectionId === "demand" ? "Fixture counts disagree." : null,
      }],
    })),
  };
}
