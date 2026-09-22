import type {
  ServiceEngagement,
  ServiceEngagementProjection,
  SurfaceState,
} from "../contracts/serviceEngagementProjection.ts";
import { buildClientSafeServiceExport } from "./exportClientSafeEngagement.ts";
import { filterEngagements, type WorkbenchFilters } from "./filterEngagements.ts";

export const WORKBENCH_FILTER_WINDOW = 500;

export type WorkbenchViewModel = {
  surface: SurfaceState;
  statusMessage: string;
  filtered: ServiceEngagement[];
  selected: ServiceEngagement | null;
  selectedIndex: number;
  exportPreview: ReturnType<typeof buildClientSafeServiceExport> | null;
  liveEndpointUnavailable: boolean;
  liveEndpointStatus: "unavailable" | "available_read_only";
  envelopeAvailability: ServiceEngagementProjection["availability"] | "unknown";
  diagnostics: string[];
  bounded: boolean;
  pipelineEmptyCopy: string | null;
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
      liveEndpointStatus: "unavailable",
      envelopeAvailability: "unknown",
      diagnostics: [],
      bounded: false,
      pipelineEmptyCopy: "Loading the service-delivery workbench.",
    };
  }

  if (!input.projection) {
    const statusMessage = input.errorMessage
      ?? "No sanitized service-engagement projection is available.";
    const unavailable = Boolean(input.errorMessage);
    return {
      surface: unavailable ? "unavailable" : "empty",
      statusMessage,
      filtered: [],
      selected: null,
      selectedIndex: -1,
      exportPreview: null,
      liveEndpointUnavailable: true,
      liveEndpointStatus: "unavailable",
      envelopeAvailability: "unknown",
      diagnostics: input.errorMessage ? [input.errorMessage] : [],
      bounded: false,
      pipelineEmptyCopy: unavailable
        ? "Canonical GET /api/service-delivery/workbench is unavailable. Demo fixtures are not substituted."
        : "No sanitized service-engagement projection is available.",
    };
  }

  const filteredAll = filterEngagements(input.projection.engagements, input.filters, {
    maxResults: WORKBENCH_FILTER_WINDOW + 1,
  });
  const bounded = filteredAll.length > WORKBENCH_FILTER_WINDOW;
  const filtered = bounded ? filteredAll.slice(0, WORKBENCH_FILTER_WINDOW) : filteredAll;
  const selected = filtered.find((item) => item.engagement_id === input.selectedId)
    ?? filtered[0]
    ?? null;
  const selectedIndex = selected
    ? filtered.findIndex((item) => item.engagement_id === selected.engagement_id)
    : -1;

  const endpointAvailableReadOnly = input.projection.live_endpoint_status === "available_read_only";
  const getSlot = endpointAvailableReadOnly ? "available_read_only" : "unavailable";
  const envelope = input.projection.availability;
  // GET slot presence never promotes fixture/manual evidence or enables mutations.
  let surface: SurfaceState = "unavailable";
  let statusMessage = `${filtered.length} engagement(s) in the current filter. Envelope: ${envelope} (not live_validated). GET slot: ${getSlot}. Source order is preserved. Economics are display copies only.`;
  if (envelope === "unavailable" && input.projection.engagements.length === 0) {
    surface = "unavailable";
    statusMessage = `Envelope: unavailable. GET slot: ${getSlot}. No sanitized engagements to review. This is not a success state.`;
  } else if (input.projection.engagements.length === 0) {
    surface = "empty";
    statusMessage = `Envelope: ${envelope}. GET slot: ${getSlot}. No engagements in the sanitized projection.`;
  } else if (filtered.length === 0) {
    surface = "empty";
    statusMessage = `Envelope: ${envelope}. GET slot: ${getSlot}. No engagements match the current filters. Clear filters to restore the source list.`;
  } else if (selected?.eligibility.data_inadequate || selected?.lifecycle_state === "data_inadequate") {
    surface = "blocked";
    statusMessage = `Envelope: ${envelope}. GET slot: ${getSlot}. Selected engagement is data_inadequate. Draft-ready is not commercially validated.`;
  } else if (selected?.stale) {
    surface = "stale";
    statusMessage = `Envelope: ${envelope}. GET slot: ${getSlot}. Selected engagement is stale. Do not treat displayed figures as current proof.`;
  } else if (envelope === "unavailable") {
    surface = "unavailable";
    statusMessage = `Envelope: unavailable. GET slot: ${getSlot}. This is not a success state and grants no mutation authority.`;
  } else if (envelope === "partial" || envelope === "fixture") {
    surface = "partial";
    statusMessage = `Envelope: ${envelope} (not live_validated). GET slot: ${getSlot}. These rows are not commercial proof.`;
  } else if (envelope === "manual_import") {
    surface = "partial";
    statusMessage = `Envelope: manual_import (not live_validated). GET slot: ${getSlot}. Plane copy only. Server order is preserved; economics are display copies only.`;
  }
  if (selected && surface !== "unavailable") {
    statusMessage = `${statusMessage} Selected lifecycle: ${selected.lifecycle_state}.`;
  }
  // Fail-closed: fixture/manual/partial/unavailable envelopes never emit success.

  return {
    surface,
    statusMessage,
    filtered,
    selected,
    selectedIndex,
    exportPreview: selected ? buildClientSafeServiceExport(selected) : null,
    liveEndpointUnavailable: !endpointAvailableReadOnly,
    liveEndpointStatus: input.projection.live_endpoint_status,
    envelopeAvailability: envelope,
    diagnostics: [
      ...(input.errorMessage ? [input.errorMessage] : []),
      ...input.projection.diagnostics,
    ],
    bounded,
    pipelineEmptyCopy: filtered.length > 0
      ? null
      : surface === "unavailable"
        ? "Canonical GET /api/service-delivery/workbench is unavailable. Demo fixtures are not substituted."
        : statusMessage.includes("Clear filters")
          ? "No engagements match. Clear filters to recover the source list."
          : "No engagements in the sanitized projection.",
  };
}

export function moveSelection(filtered: ServiceEngagement[], currentId: string | null, delta: number): string | null {
  if (!filtered.length) return null;
  const index = Math.max(0, filtered.findIndex((item) => item.engagement_id === currentId));
  const next = Math.min(filtered.length - 1, Math.max(0, index + delta));
  return filtered[next]?.engagement_id ?? null;
}

