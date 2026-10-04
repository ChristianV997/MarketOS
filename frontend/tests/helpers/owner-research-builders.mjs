/**
 * Shared TEST-ONLY builders for the owner research surface. Live-looking values
 * (evidence_mode "live_readonly", eligible:true) exist purely to prove the gate
 * and are never shipped as UI fixtures.
 */
import { importSrc } from "./load-ts.mjs";

export const NOW = Date.parse("2026-09-29T12:00:00Z");
export const FEATURE = "features/owner-research-portfolio";

const { DEMO_FIRST_PHASE_EVIDENCE_PACKET } = await importSrc("features/first-phase-cockpit/fixtures/demoPacket");

export function rankedRow(candidateId, overrides = {}) {
  const base = structuredClone(DEMO_FIRST_PHASE_EVIDENCE_PACKET.rankedCandidates[0]);
  return { ...base, candidateId, ...overrides };
}

/** A canonical ranking packet with the given rows; a recent run unless overridden. */
export function packetWith(rows, overrides = {}) {
  const packet = structuredClone(DEMO_FIRST_PHASE_EVIDENCE_PACKET);
  packet.rankedCandidates = rows;
  packet.state = "success";
  packet.blockedReasons = [];
  packet.unavailableReasons = [];
  packet.warnings = [];
  const { fingerprint, ...rest } = overrides;
  Object.assign(packet, rest);
  packet.fingerprint = {
    ...packet.fingerprint,
    generatedAt: "2026-09-29T11:00:00Z",
    freshnessLabel: null,
    ...(fingerprint ?? {}),
  };
  return packet;
}

export function portfolioPayload(overrides = {}) {
  return {
    schema_version: "owner-research-portfolio-v1",
    workspace_id: "ws-1",
    generated_at: "2026-09-29T11:00:00Z",
    evidence_mode: "live_readonly",
    items: [
      { candidate_id: "cand-a", status: "active" },
      { candidate_id: "cand-b", status: "active" },
      { candidate_id: "cand-c", status: "active" },
    ],
    draft_research: { eligible: true },
    read_only: true,
    mutated: false,
    ...overrides,
  };
}

export const CTX = { expectedWorkspaceId: "ws-1", nowMs: NOW };
