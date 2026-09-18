import type {
  ServiceEngagement,
  ServiceEngagementProjection,
  SurfaceState,
} from "../contracts/serviceEngagementProjection.ts";
import { buildClientSafeServiceExport } from "./exportClientSafeEngagement.ts";
import { filterEngagements, type WorkbenchFilters } from "./filterEngagements.ts";

export type WorkbenchViewModel = {
  surface: SurfaceState;
  statusMessage: string;
  filtered: ServiceEngagement[];
  selected: ServiceEngagement | null;
  selectedIndex: number;
  exportPreview: ReturnType<typeof buildClientSafeServiceExport> | null;
  liveEndpointUnavailable: boolean;
  diagnostics: string[];
};

export function composeWorkbenchViewModel(input: {
  isLoading: boolean;
  errorMessage: string | null;
  projection: ServiceEngagementProjection | null;
  filters: WorkbenchFilters;
  selectedId: string | null;
}): WorkbenchViewModel {
  if (input.isLoading) {
    return {
      surface: "loading",
      statusMessage: "Loading the service-delivery workbench.",
      filtered: [],
      selected: null,
      selectedIndex: -1,
      exportPreview: null,
      liveEndpointUnavailable: true,
      diagnostics: [],
    };
  }

  if (!input.projection) {
    return {
      surface: input.errorMessage ? "unavailable" : "empty",
      statusMessage: input.errorMessage
        ?? "No sanitized service-engagement projection is available.",
      filtered: [],
      selected: null,
      selectedIndex: -1,
      exportPreview: null,
      liveEndpointUnavailable: true,
      diagnostics: input.errorMessage ? [input.errorMessage] : [],
    };
  }

  const filtered = filterEngagements(input.projection.engagements, input.filters);
  const selected = filtered.find((item) => item.engagement_id === input.selectedId)
    ?? filtered[0]
    ?? null;
  const selectedIndex = selected
    ? filtered.findIndex((item) => item.engagement_id === selected.engagement_id)
    : -1;

  // Live GET remains unavailable: never emit success or live_validated for fixture/manual copies.
  let surface: SurfaceState = "unavailable";
  let statusMessage = `${filtered.length} engagement(s) in the current filter. Source order is preserved. Canonical GET ${input.projection.live_endpoint} is unavailable. Fixture/manual/simulated rows are not live client evidence.`;
  if (input.projection.availability === "unavailable" && input.projection.engagements.length === 0) {
    surface = "unavailable";
    statusMessage = "Canonical GET /api/service-delivery/workbench is unavailable. No sanitized engagements to review.";
  } else if (input.projection.engagements.length === 0) {
    surface = "empty";
    statusMessage = "No engagements in the sanitized projection.";
  } else if (filtered.length === 0) {
    surface = "empty";
    statusMessage = "No engagements match the current filters. Clear filters to restore the source list.";
  } else if (selected?.eligibility.data_inadequate || selected?.lifecycle_state === "data_inadequate") {
    surface = "blocked";
    statusMessage = "Selected engagement is data_inadequate. The client must supply the listed records. Draft-ready is not commercially validated.";
  } else if (selected?.stale) {
    surface = "stale";
    statusMessage = "Selected engagement is stale. Do not treat displayed figures as current proof.";
  } else if (input.projection.availability === "partial" || input.projection.availability === "fixture") {
    surface = "partial";
    statusMessage = "Partial/fixture projection: the live endpoint remains unavailable. These rows are not live-validated commercial proof.";
  } else if (input.projection.availability === "manual_import") {
    surface = "partial";
    statusMessage = "Manual-import / #261 plane copy. Not live-validated. Server order is preserved; economics are display copies only.";
  }

  return {
    surface,
    statusMessage,
    filtered,
    selected,
    selectedIndex,
    exportPreview: selected ? buildClientSafeServiceExport(selected) : null,
    liveEndpointUnavailable: true,
    diagnostics: [
      ...(input.errorMessage ? [input.errorMessage] : []),
      ...input.projection.diagnostics,
    ],
  };
}

export function moveSelection(filtered: ServiceEngagement[], currentId: string | null, delta: number): string | null {
  if (!filtered.length) return null;
  const index = Math.max(0, filtered.findIndex((item) => item.engagement_id === currentId));
  const next = Math.min(filtered.length - 1, Math.max(0, index + delta));
  return filtered[next]?.engagement_id ?? null;
}
