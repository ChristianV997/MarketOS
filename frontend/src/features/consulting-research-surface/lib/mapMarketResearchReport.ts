import {
  RESEARCH_SURFACE_VERSION,
  SECTION_IDS,
  type EvidenceClass,
  type SectionId,
} from "../contracts/researchSurface.ts";
import { normalizeClass } from "./adaptResearchSurface.ts";

/** Exact offline CLI / services.market_research report contract. */
export const MARKET_RESEARCH_REPORT_VERSION = "market-research-service-v1";

export type MapMarketResearchResult =
  | { ok: true; packet: Record<string, unknown> }
  | { ok: false; reason: string };

function record(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function modeToClass(mode: unknown, status: unknown): EvidenceClass {
  const statusRaw = String(status ?? "").toLowerCase();
  if (statusRaw === "missing") return "unavailable";
  const normalized = normalizeClass(mode);
  if (normalized !== "unavailable") return normalized;
  const raw = String(mode ?? "").trim().toLowerCase().replace(/-/g, "_");
  if (raw === "sanitized_report" || raw === "verified") return "derived";
  if (raw === "fixture" || raw === "fixture_demo") return "fixture";
  if (raw === "manual" || raw === "manual_import") return "manual";
  if (raw === "assumption" || raw === "assumed" || raw === "planning_assumption") return "assumed";
  if (raw === "observed" || raw === "public_observed") return "observed";
  // Never elevate live/live_validated/live_readonly through this mapper.
  if (raw === "live" || raw === "live_validated" || raw === "live_readonly" || raw === "success") {
    return "unavailable";
  }
  if (!raw) return statusRaw === "supplied" ? "derived" : "unavailable";
  return "unavailable";
}

function sectionFromPillar(pillar: string): SectionId | null {
  const raw = pillar.toLowerCase().replace(/-/g, "_");
  if (raw === "consumer_attention" || raw === "customer") return "customer";
  if (raw === "marketplace" || raw === "competitor") return "competitor";
  if (raw === "supplier") return "supplier";
  if (raw === "logistics" || raw === "delivery") return "logistics";
  if (raw === "public_market_benchmark" || raw === "pricing" || raw === "economics") return "economics";
  if (raw === "product_validation" || raw === "demand") return "demand";
  return null;
}

function summarizeBlock(block: unknown): string {
  const item = record(block);
  if (!item) return "No sanitized summary supplied.";
  if (typeof item.status === "string" && item.status.trim()) return String(item.status);
  if (typeof item.warning === "string" && item.warning.trim()) return String(item.warning);
  const keys = Object.keys(item).filter((key) => key !== "status").slice(0, 4);
  if (!keys.length) return "Empty pillar copy.";
  return keys.map((key) => `${key}=${String(item[key])}`).join("; ").slice(0, 240);
}

const SECTION_SOURCE: Record<SectionId, string> = {
  demand: "demand_and_customer_evidence",
  customer: "demand_and_customer_evidence",
  competitor: "competitor_and_substitute_evidence",
  supplier: "supplier_feasibility",
  logistics: "delivery_and_logistics_feasibility",
  economics: "pricing_and_willingness_to_pay",
};

/**
 * Reshape an offline `market-research-service-v1` report into a
 * `consulting-research-surface-v1` packet. Does not score, fuse, or invent
 * evidence — only projects already-composed report fields for the UI.
 */
export function mapMarketResearchReport(raw: unknown): MapMarketResearchResult {
  const report = record(raw);
  if (!report) return { ok: false, reason: "malformed_report" };
  if (String(report.report_version ?? "") !== MARKET_RESEARCH_REPORT_VERSION) {
    return { ok: false, reason: "unsupported_report_version" };
  }
  if (report.read_only === false || report.network_calls === true || report.mutated === true) {
    return { ok: false, reason: "unsafe_report_flags" };
  }
  if (report.external_actions_authorized === true) {
    return { ok: false, reason: "external_actions_claimed" };
  }
  const projection = record(report.client_safe_projection);
  if (projection?.external_actions_authorized === true || projection?.live_proof === true) {
    return { ok: false, reason: "live_or_execution_claim" };
  }

  const engagementId = String(report.candidate_id ?? "").trim();
  if (!engagementId) return { ok: false, reason: "missing_candidate_id" };

  const matrix = Array.isArray(report.evidence_matrix) ? report.evidence_matrix : [];
  const missingData = strings(report.missing_data);
  const conflicts = [
    ...strings(report.source_conflicts),
    ...((Array.isArray(report.conflict_findings) ? report.conflict_findings : [])
      .map((item) => {
        const row = record(item);
        if (!row) return "";
        return String(row.summary ?? row.note ?? row.field ?? "").trim();
      })
      .filter(Boolean)),
  ];

  const sections = SECTION_IDS.map((sectionId) => {
    const sourceKey = SECTION_SOURCE[sectionId];
    const block = report[sourceKey];
    const relatedMatrix = matrix.filter((item) => {
      const row = record(item);
      if (!row) return false;
      return sectionFromPillar(String(row.pillar ?? "")) === sectionId;
    });

    const rows = relatedMatrix.length
      ? relatedMatrix.map((item, index) => {
        const row = record(item) ?? {};
        const status = String(row.status ?? "unavailable");
        const conflictNote = status === "conflict"
          ? (strings(row.notes)[0] ?? conflicts[0] ?? "Source conflict recorded in report.")
          : null;
        return {
          evidence_id: `${sectionId}-${String(row.pillar ?? "row")}-${index}`,
          title: String(row.pillar ?? sectionId),
          evidence_class: modeToClass(row.evidence_mode, status),
          summary: strings(row.notes).join("; ") || summarizeBlock(block),
          source_label: "market-research-service-v1",
          captured_at: row.observed_at == null || String(row.observed_at).trim() === ""
            ? null
            : String(row.observed_at),
          fresh: status === "stale" || status === "future" ? false : null,
          conflict_note: conflictNote,
        };
      })
      : [{
        evidence_id: `${sectionId}-summary`,
        title: sectionId,
        evidence_class: modeToClass(report.evidence_class, record(block)?.status ?? "supplied"),
        summary: summarizeBlock(block),
        source_label: "market-research-service-v1",
        captured_at: null,
        fresh: null,
        conflict_note: null,
      }];

    const missing = missingData.filter((field) => {
      const lower = field.toLowerCase();
      if (sectionId === "customer" || sectionId === "demand") {
        return lower.includes("consumer") || lower.includes("demand") || lower.includes("product_validation");
      }
      if (sectionId === "competitor") return lower.includes("marketplace") || lower.includes("competitor");
      if (sectionId === "supplier") return lower.includes("supplier");
      if (sectionId === "logistics") return lower.includes("shipping") || lower.includes("logistics") || lower.includes("delivery");
      if (sectionId === "economics") {
        return lower.includes("price") || lower.includes("benchmark") || lower.includes("willingness");
      }
      return false;
    });

    return {
      section_id: sectionId,
      title: sectionId,
      rows,
      missing,
    };
  });

  const evidenceClass = String(report.evidence_class ?? "").toLowerCase();
  const availability = (
    evidenceClass.includes("fixture")
      ? "fixture"
      : evidenceClass.includes("manual")
        ? "manual"
        : "partial"
  ) as "fixture" | "manual" | "partial";

  const limitations = [
    ...strings(report.limitations),
    "Mapped from market-research-service-v1 for operator review only.",
    "Fixture, manual, assumed, and sanitized copies are not live validation or launch authority.",
  ];

  return {
    ok: true,
    packet: {
      version: RESEARCH_SURFACE_VERSION,
      engagement_id: engagementId,
      display_name: String(report.candidate_title ?? engagementId),
      offering_kind: String(report.offering_kind ?? "unknown"),
      availability,
      blockers: strings(report.blockers),
      limitations,
      next_action: String(report.next_action ?? "Review missing evidence. Do not launch."),
      sections,
      draft_only: true,
      live_validated: false,
      launch_authorized: false,
      source_report_version: MARKET_RESEARCH_REPORT_VERSION,
    },
  };
}
