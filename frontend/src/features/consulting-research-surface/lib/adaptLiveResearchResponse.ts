/**
 * Maps a live (or mocked) research report payload into the surface packet and
 * per-source observation rows. Reuses existing ingest/map adapters — does not
 * score, invent FX, or grant launch authority.
 */

import { adaptResearchSurface } from "./adaptResearchSurface.ts";
import { ingestLocalResearchReportJson } from "./loadLocalResearchReport.ts";
import type { LiveResearchSourceObservation } from "../contracts/liveResearchReport.ts";
import type { ResearchSurfaceModel } from "../contracts/researchSurface.ts";

export type LiveResearchAdaptResult =
  | {
      ok: true;
      packet: Record<string, unknown>;
      model: ResearchSurfaceModel;
      sources: LiveResearchSourceObservation[];
      evidenceLabel: "server" | "partial" | "stale";
    }
  | { ok: false; reason: string };

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function sourceStatusFromClass(
  evidenceClass: string,
  fresh: boolean | null | undefined,
): LiveResearchSourceObservation["status"] {
  if (evidenceClass === "unavailable") return "unavailable";
  if (fresh === false) return "stale";
  if (evidenceClass === "assumed" || evidenceClass === "derived") return "partial";
  if (evidenceClass === "fixture" || evidenceClass === "manual") return "partial";
  return "collected";
}

export function observationsFromSurfaceModel(model: ResearchSurfaceModel): LiveResearchSourceObservation[] {
  return model.sections.map((section) => {
    const row = section.rows[0];
    const evidenceClass = row?.evidence_class ?? "unavailable";
    const missing = section.missing.length > 0;
    let status = sourceStatusFromClass(evidenceClass, row?.fresh);
    if (missing && status === "collected") status = "partial";
    if (!row) status = "missing";
    return {
      source_id: section.section_id,
      label: section.title,
      status,
      observed_at: row?.captured_at ?? null,
      provenance: row?.source_label ?? null,
      detail: missing ? `missing: ${section.missing.join(", ")}` : row?.conflict_note ?? row?.summary ?? null,
    };
  });
}

/**
 * Accept only MRS / CRS shaped JSON already produced by a server (or test mock).
 * Secret-shaped and mismatched contracts fail closed without echoing payload.
 */
export function adaptLiveResearchResponse(payload: unknown): LiveResearchAdaptResult {
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

  const adapted = adaptResearchSurface(ingested.packet);
  if (adapted.rejected || !adapted.model) {
    return { ok: false, reason: adapted.reason ?? "surface_rejected" };
  }

  // Live transport must never present fixture availability as authenticated live.
  const availability = String(adapted.model.availability ?? "").toLowerCase();
  if (availability === "fixture") {
    return { ok: false, reason: "fixture_packet_rejected_on_live_transport" };
  }

  const sources = observationsFromSurfaceModel(adapted.model);
  const anyStale = sources.some((item) => item.status === "stale");
  const anyPartial = sources.some((item) => item.status === "partial" || item.status === "missing" || item.status === "unavailable");
  const evidenceLabel: "server" | "partial" | "stale" = anyStale ? "stale" : anyPartial ? "partial" : "server";

  return {
    ok: true,
    packet: ingested.packet,
    model: adapted.model,
    sources,
    evidenceLabel,
  };
}

/** Test helper: wrap a surface/MRS packet as a transport envelope if needed. */
export function unwrapLiveResearchEnvelope(payload: unknown): unknown {
  const record = asRecord(payload);
  if (!record) return payload;
  if (record.report != null) return record.report;
  if (record.packet != null) return record.packet;
  return payload;
}
