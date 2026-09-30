import type { MoneyValue, OwnerCandidate, RatioValue } from "../contracts/ownerDashboard.ts";
import { NOT_AVAILABLE, formatMoney, formatPercent, formatRatio } from "./decimal.ts";

export function moneyText(value: MoneyValue): string {
  return value.kind === "amount" ? formatMoney(value.numeric, value.currency) : NOT_AVAILABLE;
}

export function ratioText(value: RatioValue | undefined, style: "percent" | "multiple"): string {
  if (!value || value.kind === "unavailable") return NOT_AVAILABLE;
  return style === "percent" ? formatPercent(value.numeric) : `${formatRatio(value.numeric)}×`;
}

export function scoreText(score: number | null): string {
  return score === null ? NOT_AVAILABLE : score.toFixed(3);
}

export function confidenceText(confidence: number | null): string {
  return confidence === null ? NOT_AVAILABLE : formatPercent(confidence, 0);
}

export function rankText(rank: number | null): string {
  return rank === null ? "Not ranked" : `#${rank}`;
}

/** Reads only what the provider reported. "No gaps reported" is not "evidence is complete". */
export function evidenceStatusText(candidate: OwnerCandidate): string {
  const gaps = candidate.evidenceGaps.length;
  if (gaps > 0) return `${gaps} evidence ${gaps === 1 ? "gap" : "gaps"}`;
  if (candidate.evidence.length === 0) return "No evidence items provided";
  return "No evidence gaps reported";
}
