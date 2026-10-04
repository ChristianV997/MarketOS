/**
 * Offline fixtures for design review and tests. They are ALWAYS labelled
 * fixture_only, so the surface shows the fixture banner and refuses to enable
 * draft research. They are only used when a caller explicitly asks for the
 * fixture source; the live path never falls back to them.
 */

import { DEMO_FIRST_PHASE_EVIDENCE_PACKET } from "../../first-phase-cockpit/fixtures/demoPacket";
import type { FirstPhaseEvidencePacket } from "../../first-phase-cockpit/contracts/firstPhaseEvidencePacket";
import {
  OWNER_PORTFOLIO_SCHEMA_VERSION,
  type OwnerPortfolioReadModelV1,
} from "../contracts/ownerResearch";

export const FIXTURE_WORKSPACE_ID = "ws-fixture-owner";

/** Reuses the cockpit's deterministic demo packet: no parallel ranking data. */
export const FIXTURE_RANKING_PACKET: FirstPhaseEvidencePacket = DEMO_FIRST_PHASE_EVIDENCE_PACKET;

/**
 * Two distinct active candidates expressed as several rows (extra SKU, offers,
 * quantity) plus removed/inactive entries: the count must stay 2/3.
 */
export const FIXTURE_PORTFOLIO_PAYLOAD: OwnerPortfolioReadModelV1 = {
  schema_version: OWNER_PORTFOLIO_SCHEMA_VERSION,
  workspace_id: FIXTURE_WORKSPACE_ID,
  generated_at: "2026-09-02T00:00:00Z",
  evidence_mode: "fixture_only",
  items: [
    { candidate_id: "cand-espresso-01", status: "active", sku: "FIX-ESP-01", supplier_offer_count: 3, quantity: 40 },
    { candidate_id: "cand-espresso-01", status: "active", sku: "FIX-ESP-01-B", supplier_offer_count: 1, quantity: 12 },
    { candidate_id: "cand-bottle-02", status: "active", sku: "FIX-BTL-02", quantity: 200 },
    { candidate_id: "hydroponics-kit", status: "removed", sku: "HYDRO-KIT-01" },
    { candidate_id: "commodity-usb-cable", status: "inactive", sku: "USB-C-COMMODITY" },
  ],
  draft_research: { eligible: false, reasons: ["fixture_portfolio_is_not_live_evidence"] },
  read_only: true,
  mutated: false,
  network_calls: false,
};
