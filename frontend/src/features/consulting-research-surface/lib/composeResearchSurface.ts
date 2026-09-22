import type { ResearchSurfaceModel, SectionId, SurfaceState } from "../contracts/researchSurface.ts";
import { buildClientSafeSurfaceExport } from "./exportResearchSurface.ts";

export interface ResearchSurfaceView {
  state: SurfaceState;
  message: string;
  model: ResearchSurfaceModel;
  selectedSectionId: SectionId | null;
  conflicts: { section_id: SectionId; note: string }[];
  missing: { section_id: SectionId; field: string }[];
  exportPreview: ReturnType<typeof buildClientSafeSurfaceExport>;
  launchAuthorized: false;
  fixtureIsSuccess: false;
}

export function sectionIds(model: ResearchSurfaceModel): SectionId[] {
  return model.sections.map((section) => section.section_id);
}

export function moveSelection(order: SectionId[], current: SectionId | null, key: string): SectionId | null {
  if (order.length === 0) return null;
  const index = current == null ? -1 : order.indexOf(current);
  if (key === "Home") return order[0];
  if (key === "End") return order[order.length - 1];
  if (key === "ArrowDown" || key === "ArrowRight") return order[Math.min(order.length - 1, index + 1)];
  if (key === "ArrowUp" || key === "ArrowLeft") return order[Math.max(0, (index < 0 ? 0 : index) - 1)];
  return current;
}

export function composeResearchSurface(input: {
  loading: boolean;
  errorMessage: string | null;
  model: ResearchSurfaceModel;
  rejected: boolean;
  selectedSectionId: SectionId | null;
}): ResearchSurfaceView {
  const order = sectionIds(input.model);
  const selected = input.selectedSectionId && order.includes(input.selectedSectionId) ? input.selectedSectionId : order[0] ?? null;
  const conflicts = input.model.sections.flatMap((section) => section.rows
    .filter((row) => row.conflict_note)
    .map((row) => ({ section_id: section.section_id, note: row.conflict_note as string })));
  const missing = input.model.sections.flatMap((section) => section.missing.map((field) => ({ section_id: section.section_id, field })));
  const stale = input.model.sections.some((section) => section.rows.some((row) => row.fresh === false));
  let state: SurfaceState = "partial";
  if (input.loading) state = "loading";
  else if (input.errorMessage || input.rejected || input.model.availability === "unavailable") state = input.errorMessage ? "error" : "unavailable";
  else if (order.length === 0) state = "empty";
  else if (input.model.blockers.length > 0) state = "blocked";
  else if (stale) state = "stale";
  const message = state === "loading"
    ? "Loading research sections."
    : state === "error"
      ? input.errorMessage ?? "Research surface error."
      : state === "unavailable"
        ? "Packet unavailable. Fixture and manual evidence are not live validation."
        : state === "empty"
          ? "No research sections were supplied."
          : `${input.model.availability} evidence. Not a success state. Not launch authorized.`;
  return {
    state,
    message,
    model: input.model,
    selectedSectionId: selected,
    conflicts,
    missing,
    exportPreview: buildClientSafeSurfaceExport(input.model),
    launchAuthorized: false,
    fixtureIsSuccess: false,
  };
}
