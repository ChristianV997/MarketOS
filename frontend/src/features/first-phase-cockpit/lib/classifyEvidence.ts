import {
  LIVE_PROOF_EVIDENCE_CLASSES,
  type EvidenceClass,
  type EvidenceMode,
  type PillarId,
} from "../contracts/firstPhaseEvidencePacket";

const OFFLINE_MODES: ReadonlySet<EvidenceMode> = new Set([
  "fixture_only",
  "manual",
  "simulated",
  "unknown",
]);

function parseDeclaredClass(value: string | null | undefined): EvidenceClass | null {
  if (!value) return null;
  const lowered = value.toLowerCase().replace(/-/g, "_");
  if (lowered.includes("live_sales") || lowered.includes("sales_validated")) return "live_sales_validated";
  if (lowered.includes("live_order") || lowered.includes("order_verified")) return "live_order_verified";
  if (lowered.includes("sample_verified") || lowered.includes("sample")) return "sample_verified";
  if (lowered.includes("supplier_documented") || lowered.includes("documented")) return "supplier_documented";
  if (lowered.includes("supplier_claimed") || lowered.includes("claimed")) return "supplier_claimed";
  if (lowered.includes("public_observed") || lowered.includes("public")) return "public_observed";
  if (lowered.includes("assumption")) return "assumption";
  if (lowered.includes("derived")) return "derived";
  if (lowered.includes("fixture")) return "fixture";
  if (lowered.includes("unavailable")) return "unavailable";
  if (lowered.includes("blocked")) return "blocked";
  return null;
}

/**
 * Map run mode + source family + optional declared class without inventing live proof.
 * Fixture/manual/simulated never become sample_verified, live_order_verified, or live_sales_validated.
 */
export function classifyEvidenceClass(input: {
  evidenceMode: EvidenceMode;
  sourceFamily?: string | null;
  pillarId?: PillarId | null;
  declared?: string | null;
  status?: "available" | "partial" | "unavailable" | "blocked" | null;
}): EvidenceClass {
  if (input.status === "unavailable") return "unavailable";
  if (input.status === "blocked") return "blocked";

  const declared = parseDeclaredClass(input.declared);
  const offline = OFFLINE_MODES.has(input.evidenceMode);

  if (declared && LIVE_PROOF_EVIDENCE_CLASSES.has(declared) && offline) {
    if (input.evidenceMode === "fixture_only") return "fixture";
    if (input.evidenceMode === "manual") return "supplier_claimed";
    return "derived";
  }

  if (declared && (!LIVE_PROOF_EVIDENCE_CLASSES.has(declared) || !offline)) {
    if (LIVE_PROOF_EVIDENCE_CLASSES.has(declared) && input.evidenceMode !== "live_readonly") {
      return "unavailable";
    }
    return declared;
  }

  if (input.evidenceMode === "fixture_only") return "fixture";
  if (input.pillarId === "economics") return "assumption";
  if (input.pillarId === "freshness" || input.pillarId === "provenance") return "derived";
  if (input.pillarId === "consumer_attention") return "unavailable";

  const family = (input.sourceFamily ?? "").toLowerCase();
  if (family.includes("public_market") && input.evidenceMode === "live_readonly") return "public_observed";
  if (family.includes("public_market")) return input.evidenceMode === "manual" ? "supplier_claimed" : "fixture";
  if (input.pillarId === "supplier_feasibility") {
    if (input.evidenceMode === "live_readonly") return "supplier_documented";
    if (input.evidenceMode === "manual") return "supplier_claimed";
    return "fixture";
  }
  if (input.evidenceMode === "manual") return "supplier_claimed";
  if (input.evidenceMode === "simulated") return "derived";
  if (input.evidenceMode === "live_readonly") return "public_observed";
  return "unavailable";
}

export function isLiveProofEvidenceClass(value: EvidenceClass): boolean {
  return LIVE_PROOF_EVIDENCE_CLASSES.has(value);
}
