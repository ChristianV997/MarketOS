import type { PromotionState } from "../contracts/firstPhaseEvidencePacket";

/** Map commercial_decision to a non-authoritative promotion label. Never "launched". */
export function derivePromotionState(decision: string | null | undefined): PromotionState {
  if (!decision) return "unavailable";
  const lowered = decision.toLowerCase();
  if (lowered.includes("reject")) return "reject";
  if (lowered.includes("block")) return "blocked";
  if (lowered.includes("defer")) return "defer";
  if (lowered.includes("hold") || lowered.includes("review") || lowered.includes("credential")) {
    return "hold";
  }
  return "hold";
}
