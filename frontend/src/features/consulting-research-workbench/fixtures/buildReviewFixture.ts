import { CONSULTING_RESEARCH_REVIEW_VERSION, SECTION_IDS } from "../contracts/consultingResearchReview.ts";

export function buildReviewFixture() {
  return {
    review_version: CONSULTING_RESEARCH_REVIEW_VERSION,
    engagement_id: "consult-fixture-alpha",
    display_name: "Example fixture engagement",
    offering_kind: "market_scan",
    research_question: "Is the stated offer distinct from the named competitors in this fixture?",
    scope: "Fixture packet only. No live crawl, no supplier contact, no launch.",
    availability: "fixture",
    confidence_label: null,
    limitations: ["Fixture rows are screening copy. They are not live validation."],
    blockers: ["Supplier identity is missing."],
    next_action: "Collect the missing supplier record before any client review.",
    sections: SECTION_IDS.map((sectionId) => ({
      section_id: sectionId,
      question: `What does the ${sectionId} fixture show?`,
      missing: sectionId === "supplier" ? ["supplier_legal_name"] : [],
      items: [{
        evidence_id: `${sectionId}-1`,
        title: `${sectionId} fixture note`,
        evidence_class: sectionId === "economics" ? "assumed" : "fixture",
        summary: "Supplied fixture copy.",
        source_label: "fixture-packet",
        captured_at: null,
        fresh: sectionId === "competitor" ? false : null,
        conflict_note: sectionId === "demand" ? "Two fixture counts disagree." : null,
      }],
    })),
    timeline: [
      { event_id: "tl-1", label: "Fixture packet assembled", at: null, evidence_class: "fixture" },
    ],
  };
}
