import { RESEARCH_SURFACE_VERSION } from "../contracts/researchSurface.ts";
import { adaptResearchSurface } from "./adaptResearchSurface.ts";
import { mapMarketResearchReport, MARKET_RESEARCH_REPORT_VERSION } from "./mapMarketResearchReport.ts";

/** Strict in-browser cap for operator-selected report JSON (memory-only). */
export const MAX_LOCAL_RESEARCH_REPORT_BYTES = 512 * 1024;

const SECRET = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}|-----begin |xoxb-|aiza/i;
const LEAK = /(cross[ _-]?client|cross[ _-]?workspace|another[ _-]?client|internal[ _-]?prompt|internal[ _-]?formula|raw[ _-]?payload|api[ _-]?key|heuristic[ _-]?weight)/i;

export type LocalReportLoadResult =
  | { ok: true; packet: Record<string, unknown>; source: "consulting-research-surface-v1" | "market-research-service-v1" }
  | { ok: false; reason: string };

function record(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function leaky(value: unknown): boolean {
  if (typeof value === "string") return SECRET.test(value) || LEAK.test(value);
  if (Array.isArray(value)) return value.some(leaky);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
    if (SECRET.test(key) || LEAK.test(key)) return true;
    return leaky(item);
  });
}

/** Reject unsafe/mismatched JSON without echoing payload contents into the reason. */
export function ingestLocalResearchReportJson(text: string): LocalReportLoadResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, reason: "invalid_json" };
  }
  if (leaky(parsed)) {
    return { ok: false, reason: "prohibited_or_secret_shaped" };
  }
  const packet = record(parsed);
  if (!packet) return { ok: false, reason: "malformed_object" };

  const version = String(packet.version ?? packet.review_version ?? "");
  const reportVersion = String(packet.report_version ?? "");

  if (version === RESEARCH_SURFACE_VERSION) {
    const adapted = adaptResearchSurface(packet);
    if (adapted.rejected) {
      return { ok: false, reason: adapted.reason ?? "surface_rejected" };
    }
    return { ok: true, packet, source: "consulting-research-surface-v1" };
  }

  if (reportVersion === MARKET_RESEARCH_REPORT_VERSION) {
    const mapped = mapMarketResearchReport(packet);
    if (!mapped.ok) return { ok: false, reason: mapped.reason };
    if (leaky(mapped.packet)) return { ok: false, reason: "prohibited_or_secret_shaped" };
    const adapted = adaptResearchSurface(mapped.packet);
    if (adapted.rejected) {
      return { ok: false, reason: adapted.reason ?? "surface_rejected" };
    }
    return { ok: true, packet: mapped.packet, source: "market-research-service-v1" };
  }

  return { ok: false, reason: "unsupported_contract" };
}

export async function loadLocalResearchReportFile(file: File): Promise<LocalReportLoadResult> {
  if (!file) return { ok: false, reason: "missing_file" };
  if (typeof file.size === "number" && file.size > MAX_LOCAL_RESEARCH_REPORT_BYTES) {
    return { ok: false, reason: "file_too_large" };
  }
  const text = await file.text();
  // Defense in depth: UTF-8 byte length can exceed size for some engines' File.size.
  if (new TextEncoder().encode(text).length > MAX_LOCAL_RESEARCH_REPORT_BYTES) {
    return { ok: false, reason: "file_too_large" };
  }
  return ingestLocalResearchReportJson(text);
}

export function localReportRejectionMessage(reason: string): string {
  switch (reason) {
    case "invalid_json":
      return "Selected file is not valid JSON. Payload not shown.";
    case "file_too_large":
      return `Selected file exceeds the ${MAX_LOCAL_RESEARCH_REPORT_BYTES} byte limit. Payload not shown.`;
    case "prohibited_or_secret_shaped":
      return "Selected file contains prohibited or secret-shaped content and was rejected. Payload not shown.";
    case "unsupported_contract":
      return "Selected file is not consulting-research-surface-v1 or market-research-service-v1. Payload not shown.";
    case "unsupported_report_version":
    case "malformed_report":
    case "malformed_object":
    case "missing_candidate_id":
    case "unsafe_report_flags":
    case "external_actions_claimed":
    case "live_or_execution_claim":
      return "Selected report failed contract checks and was rejected. Payload not shown.";
    default:
      return "Selected report was rejected. Payload not shown.";
  }
}
