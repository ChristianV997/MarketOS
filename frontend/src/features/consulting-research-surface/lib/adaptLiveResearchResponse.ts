/**
 * Maps a live (or mocked) research report payload into the surface packet and
 * per-row observation list. Reuses existing ingest/map adapters — does not
 * score, invent FX, or grant launch authority.
 *
 * Integrity rules for live transport:
 * - Every section row becomes an observation (never only rows[0]).
 * - Evidence status is derived only from an explicit, recognized evidence_class.
 * - Unknown / missing classes reject the payload (no optimistic "collected").
 * - Fixture-shaped packets or fixture rows are rejected on live transport.
 * - A structurally valid response is not source verification.
 */

import { adaptResearchSurface } from "./adaptResearchSurface.ts";
import { ingestLocalResearchReportJson } from "./loadLocalResearchReport.ts";
import type { LiveResearchSourceObservation, LiveResearchSourceStatus } from "../contracts/liveResearchReport.ts";
import {
  EVIDENCE_CLASSES,
  type EvidenceClass,
  type EvidenceRow,
  type ResearchSurfaceModel,
} from "../contracts/researchSurface.ts";

/** Packet-level honesty label — never claims live verification. */
export type LiveResearchEvidenceLabel = "observed" | "partial" | "stale" | "mixed";

export type LiveResearchAdaptResult =
  | {
      ok: true;
      packet: Record<string, unknown>;
      model: ResearchSurfaceModel;
      sources: LiveResearchSourceObservation[];
      evidenceLabel: LiveResearchEvidenceLabel;
    }
  | { ok: false; reason: string };

const RECOGNIZED_CLASSES = new Set<string>(EVIDENCE_CLASSES);
/** Aliases accepted on the documented CRS contract before normalization. */
const ACCEPTED_CLASS_ALIASES = new Set([
  "manual_import",
  "fixture_only",
  "fixture_demo",
  "assumption",
]);
const REJECTED_LIVE_CLAIMS = new Set(["live", "live_validated", "live_readonly", "success"]);

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

/**
 * Inspect CRS packet rows before normalizeClass can hide unknown/live claims.
 * Returns a stable reason string or null when the packet is acceptable.
 */
export function assertLiveEvidenceClasses(packet: Record<string, unknown>): string | null {
  const sections = packet.sections;
  if (!Array.isArray(sections)) return "malformed_section_rows";

  for (const rawSection of sections) {
    const section = asRecord(rawSection);
    if (!section) return "malformed_section_rows";
    const rows = section.rows;
    if (!Array.isArray(rows)) return "malformed_section_rows";
    for (const rawRow of rows) {
      const row = asRecord(rawRow);
      if (!row) return "malformed_evidence_row";
      if (row.evidence_class == null || row.evidence_class === "") {
        return "missing_evidence_class";
      }
      const raw = String(row.evidence_class).trim().toLowerCase().replace(/-/g, "_");
      if (REJECTED_LIVE_CLAIMS.has(raw)) return "live_claim_rejected_on_live_transport";
      if (raw === "fixture" || raw === "fixture_only" || raw === "fixture_demo") {
        return "fixture_row_rejected_on_live_transport";
      }
      if (!RECOGNIZED_CLASSES.has(raw) && !ACCEPTED_CLASS_ALIASES.has(raw)) {
        return "unrecognized_evidence_class";
      }
    }
  }
  return null;
}

/**
 * Map a recognized evidence class (+ freshness/conflict) to a display status.
 * Returns null when the class is missing or unrecognized (caller must reject).
 */
export function mapRecognizedEvidenceStatus(
  evidenceClass: unknown,
  fresh: boolean | null | undefined,
  conflictNote: string | null | undefined,
): LiveResearchSourceStatus | null {
  if (evidenceClass == null || evidenceClass === "") return null;
  const raw = String(evidenceClass).trim().toLowerCase().replace(/-/g, "_");
  if (!RECOGNIZED_CLASSES.has(raw)) return null;

  const cls = raw as EvidenceClass;
  if (cls === "unavailable") return "unavailable";
  if (cls === "fixture" || cls === "manual" || cls === "assumed" || cls === "derived") return "partial";
  // observed only
  if (fresh === false) return "stale";
  if (conflictNote && String(conflictNote).trim()) return "partial";
  return "collected";
}

function observationFromRow(
  sectionId: string,
  sectionTitle: string,
  row: EvidenceRow,
  missing: string[],
): { ok: true; observation: LiveResearchSourceObservation } | { ok: false; reason: string } {
  const status = mapRecognizedEvidenceStatus(row.evidence_class, row.fresh, row.conflict_note);
  if (status == null) {
    return { ok: false, reason: "unrecognized_evidence_class" };
  }
  if (row.evidence_class === "fixture") {
    return { ok: false, reason: "fixture_row_rejected_on_live_transport" };
  }

  let finalStatus: LiveResearchSourceStatus = status;
  if (missing.length > 0 && finalStatus === "collected") finalStatus = "partial";

  const detailParts: string[] = [];
  if (missing.length > 0) detailParts.push(`missing: ${missing.join(", ")}`);
  if (row.conflict_note) detailParts.push(row.conflict_note);
  if (row.summary) detailParts.push(row.summary);

  return {
    ok: true,
    observation: {
      source_id: `${sectionId}:${row.evidence_id}`,
      label: `${sectionTitle} · ${row.title}`,
      status: finalStatus,
      observed_at: row.captured_at ?? null,
      provenance: row.source_label ?? null,
      detail: detailParts.length ? detailParts.join(" · ") : null,
    },
  };
}

/**
 * Build one observation per evidence row. Rejects ambiguous/unsafe models.
 * Empty sections with listed missing fields emit a single `missing` observation.
 */
export function observationsFromSurfaceModel(
  model: ResearchSurfaceModel,
): { ok: true; sources: LiveResearchSourceObservation[] } | { ok: false; reason: string } {
  const sources: LiveResearchSourceObservation[] = [];

  for (const section of model.sections) {
    if (!Array.isArray(section.rows)) {
      return { ok: false, reason: "malformed_section_rows" };
    }

    if (section.rows.length === 0) {
      sources.push({
        source_id: `${section.section_id}:_empty`,
        label: section.title,
        status: section.missing.length > 0 ? "missing" : "unavailable",
        observed_at: null,
        provenance: null,
        detail: section.missing.length > 0 ? `missing: ${section.missing.join(", ")}` : "no evidence rows",
      });
      continue;
    }

    for (const row of section.rows) {
      if (!row || typeof row !== "object") {
        return { ok: false, reason: "malformed_evidence_row" };
      }
      if (row.evidence_class == null || row.evidence_class === ("" as EvidenceClass)) {
        return { ok: false, reason: "missing_evidence_class" };
      }
      const mapped = observationFromRow(section.section_id, section.title, row, section.missing);
      if (!mapped.ok) return mapped;
      sources.push(mapped.observation);
    }
  }

  return { ok: true, sources };
}

function labelFromSources(sources: LiveResearchSourceObservation[]): LiveResearchEvidenceLabel {
  const statuses = new Set(sources.map((item) => item.status));
  if (statuses.has("stale")) {
    return statuses.size === 1 ? "stale" : "mixed";
  }
  const nonCollected = [...statuses].filter((status) => status !== "collected");
  if (nonCollected.length === 0) return "observed";
  if (statuses.has("collected") && nonCollected.length > 0) return "mixed";
  return "partial";
}

/**
 * Accept only MRS / CRS shaped JSON already produced by a server (or test mock).
 * Secret-shaped and mismatched contracts fail closed without echoing payload.
 */
export function adaptLiveResearchResponse(payload: unknown): LiveResearchAdaptResult {
  if (payload == null) return { ok: false, reason: "malformed_payload" };
  if (typeof payload !== "object") return { ok: false, reason: "malformed_payload" };

  const text = (() => {
    try {
      return JSON.stringify(payload);
    } catch {
      return null;
    }
  })();
  if (text == null) return { ok: false, reason: "unserializable_payload" };

  const ingested = ingestLocalResearchReportJson(text);
  if (!ingested.ok) return { ok: false, reason: ingested.reason };

  // Live transport must never present fixture availability as authenticated live.
  const availabilityRaw = String(ingested.packet.availability ?? "").toLowerCase();
  if (availabilityRaw === "fixture") {
    return { ok: false, reason: "fixture_packet_rejected_on_live_transport" };
  }

  const classIssue = assertLiveEvidenceClasses(ingested.packet);
  if (classIssue) return { ok: false, reason: classIssue };

  const adapted = adaptResearchSurface(ingested.packet);
  if (adapted.rejected || !adapted.model) {
    return { ok: false, reason: adapted.reason ?? "surface_rejected" };
  }

  const availability = String(adapted.model.availability ?? "").toLowerCase();
  if (availability === "fixture") {
    return { ok: false, reason: "fixture_packet_rejected_on_live_transport" };
  }

  const observed = observationsFromSurfaceModel(adapted.model);
  if (!observed.ok) return { ok: false, reason: observed.reason };

  return {
    ok: true,
    packet: ingested.packet,
    model: adapted.model,
    sources: observed.sources,
    evidenceLabel: labelFromSources(observed.sources),
  };
}

/** Unwrap optional transport envelopes; does not treat arbitrary keys as authority. */
export function unwrapLiveResearchEnvelope(payload: unknown): unknown {
  const record = asRecord(payload);
  if (!record) return payload;
  if (record.report != null) return record.report;
  if (record.packet != null) return record.packet;
  return payload;
}
