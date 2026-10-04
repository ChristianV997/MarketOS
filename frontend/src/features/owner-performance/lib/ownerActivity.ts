import type { EventQueryParams } from "../../../lib/canonicalEventsApi.ts";

/** First bounded page from GET /api/events; deliberately no cursor protocol. */
export const OWNER_ACTIVITY_QUERY: Readonly<EventQueryParams> = Object.freeze({
  limit: 10,
  offset: 0,
});

export interface OwnerActivityEvent {
  eventId: string;
  eventType: string;
  occurredAt: number;
  sourceLabel: string;
  evidenceLabels: string[];
  authorityFlags: string[];
  sourceQualification: string;
}

export type OwnerActivityState =
  | { phase: "loading" }
  | { phase: "empty" }
  | { phase: "error"; message: string }
  | { phase: "unavailable"; message: string }
  | {
      phase: "ready";
      events: OwnerActivityEvent[];
      freshnessTimestamp: number | null;
      warnings: string[];
      query: Readonly<EventQueryParams>;
    };

export const OWNER_ACTIVITY_UNAVAILABLE: OwnerActivityState = Object.freeze({
  phase: "unavailable",
  message:
    "GET /api/events has no server-verified owner workspace boundary. Its optional workspace_id is only a client selector, so this owner view does not request or display events until the route enforces caller-bound workspace access.",
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sourceQualification(source: string): string {
  if (source === "manual") return "Manual evidence; not a live observation";
  if (source === "fixture") return "Fixture data; not a live observation";
  return "Source labels are preserved; they do not prove live validation";
}

function eventEvidenceLabels(event: Record<string, unknown>): string[] {
  const labels: string[] = [];
  if (event.dry_run === true) labels.push("Dry run");
  if (event.advisory === true) labels.push("Advisory");
  if (event.read_only === true) labels.push("Read only");
  return labels;
}

function eventAuthorityFlags(event: Record<string, unknown>): string[] {
  if (
    !Array.isArray(event.authority_flags) ||
    event.authority_flags.some((flag) => typeof flag !== "string")
  ) {
    throw new Error("Canonical event authority flags are invalid.");
  }
  return [...event.authority_flags];
}

/**
 * Adapts the existing GET /api/events response without changing its identity,
 * event order, provenance labels, or limit/offset semantics.
 */
export function presentCanonicalEventResponse(
  response: unknown,
  query: Readonly<EventQueryParams> = OWNER_ACTIVITY_QUERY,
): OwnerActivityState {
  try {
    return presentCanonicalEventResponseUnchecked(response, query);
  } catch (error) {
    return {
      phase: "error",
      message: error instanceof Error ? error.message : "Canonical event response is invalid.",
    };
  }
}

function presentCanonicalEventResponseUnchecked(
  response: unknown,
  query: Readonly<EventQueryParams>,
): OwnerActivityState {
  if (!isRecord(response) || !isRecord(response.timeline)) {
    throw new Error("Canonical event response did not include a timeline.");
  }

  const timeline = response.timeline;
  if (!Array.isArray(timeline.events)) {
    throw new Error("Canonical event timeline did not include an events array.");
  }

  if (
    !Array.isArray(timeline.warnings) ||
    timeline.warnings.some((warning) => typeof warning !== "string")
  ) {
    throw new Error("Canonical event warnings are invalid.");
  }
  const warnings = [...timeline.warnings];

  if (timeline.events.length === 0) {
    if (warnings.length > 0) {
      return {
        phase: "unavailable",
        message: `Canonical event source is not configured or readable (${warnings.join(", ")}).`,
      };
    }
    return { phase: "empty" };
  }

  const eventIds = new Set<string>();
  const events = timeline.events.map((value): OwnerActivityEvent => {
    if (
      !isRecord(value) ||
      typeof value.event_id !== "string" ||
      typeof value.event_type !== "string" ||
      typeof value.occurred_at !== "number" ||
      !Number.isFinite(value.occurred_at) ||
      typeof value.source !== "string"
    ) {
      throw new Error("Canonical event record is missing its identity, timestamp, type, or source label.");
    }
    if (eventIds.has(value.event_id)) {
      throw new Error("Canonical event timeline contains duplicate event identities.");
    }
    eventIds.add(value.event_id);

    return {
      eventId: value.event_id,
      eventType: value.event_type,
      occurredAt: value.occurred_at,
      sourceLabel: value.source,
      evidenceLabels: eventEvidenceLabels(value),
      authorityFlags: eventAuthorityFlags(value),
      sourceQualification: sourceQualification(value.source),
    };
  });

  const freshnessTimestamp = timeline.last_occurred_at;
  if (
    freshnessTimestamp !== null &&
    (typeof freshnessTimestamp !== "number" || !Number.isFinite(freshnessTimestamp))
  ) {
    throw new Error("Canonical event freshness timestamp is invalid.");
  }

  return {
    phase: "ready",
    events,
    freshnessTimestamp: freshnessTimestamp as number | null,
    warnings,
    query: Object.freeze({ ...query }),
  };
}
