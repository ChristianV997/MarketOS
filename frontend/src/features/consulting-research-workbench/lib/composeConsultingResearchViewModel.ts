import type { ConsultingResearchReview, SectionId } from "../contracts/consultingResearchReview.ts";
import { buildClientSafeReviewExport } from "./exportClientSafeReview.ts";

export type SurfaceState = "loading" | "empty" | "blocked" | "unavailable" | "partial" | "stale";

export interface ConsultingResearchViewModel {
  surface: SurfaceState;
  statusMessage: string;
  review: ConsultingResearchReview;
  selectedSectionId: SectionId | null;
  exportPreview: ReturnType<typeof buildClientSafeReviewExport> | null;
  liveProof: false;
  launchAuthorized: false;
}

export function sectionOrder(review: ConsultingResearchReview): SectionId[] {
  return review.sections.map((section) => section.section_id);
}

export function moveSection(order: SectionId[], current: SectionId | null, key: string): SectionId | null {
  if (order.length === 0) return null;
  const index = current ? order.indexOf(current) : 0;
  if (key === "Home") return order[0];
  if (key === "End") return order[order.length - 1];
  if (key === "ArrowDown" || key === "ArrowRight") return order[Math.min(order.length - 1, Math.max(0, index) + 1)];
  if (key === "ArrowUp" || key === "ArrowLeft") return order[Math.max(0, (index < 0 ? 0 : index) - 1)];
  return current;
}

export function composeConsultingResearchViewModel(input: {
  isLoading: boolean;
  review: ConsultingResearchReview;
  rejected: boolean;
  selectedSectionId: SectionId | null;
}): ConsultingResearchViewModel {
  const order = sectionOrder(input.review);
  const selected = input.selectedSectionId && order.includes(input.selectedSectionId)
    ? input.selectedSectionId
    : order[0] ?? null;
  const selectedSection = input.review.sections.find((section) => section.section_id === selected) ?? null;
  const stale = input.review.sections.some((section) => section.items.some((item) => item.fresh === false));
  let surface: SurfaceState = "partial";
  if (input.isLoading) surface = "loading";
  else if (input.rejected || input.review.availability === "unavailable") surface = "unavailable";
  else if (input.review.blockers.length > 0) surface = "blocked";
  else if (order.length === 0) surface = "empty";
  else if (stale) surface = "stale";
  else surface = "partial";
  const statusMessage = surface === "loading"
    ? "Loading the research review."
    : surface === "unavailable"
      ? "Research packet unavailable. Fixture and manual evidence are not live validation."
      : `${input.review.availability} evidence. Not live validated. Not launch authorized.`;
  return {
    surface,
    statusMessage,
    review: input.review,
    selectedSectionId: selected,
    exportPreview: selectedSection ? buildClientSafeReviewExport(input.review) : null,
    liveProof: false,
    launchAuthorized: false,
  };
}
