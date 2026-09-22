import type { PromotionState } from "../contracts/firstPhaseEvidencePacket.ts";

/** Map commercial_decision to a non-authoritative promotion label. Never "launched". */
export function derivePromotionState(decision: string | null | undefined): PromotionState {
  if (!decision) return "unavailable";
  const lowered = decision.toLowerCase();
  if (lowered.includes("launch") && !lowered.includes("false") && !lowered.includes("draft")) {
    return "unavailable";
  }
  if (lowered.includes("reject")) return "reject";
  if (lowered.includes("block")) return "blocked";
  if (lowered.includes("defer")) return "defer";
  if (lowered.includes("draft_ready") || lowered.includes("draft-ready") || lowered === "draft") {
    return "draft_ready";
  }
  if (lowered.includes("needs_evidence") || lowered.includes("missing_evidence") || lowered.includes("inadequate")) {
    return "needs_evidence";
  }
  if (lowered.includes("screen")) return "screening";
  if (lowered.includes("hold") || lowered.includes("review") || lowered.includes("credential")) {
    return "hold";
  }
  return "hold";
}
