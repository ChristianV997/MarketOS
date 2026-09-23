import type { MarketingStrategyPacket } from "../contracts/marketingStrategyPacket.ts";
import { composeStrategyView } from "./composeStrategyView.ts";

const OMIT = [
  "prompt",
  "formula",
  "heuristic",
  "credential",
  "secret",
  "raw_payload",
  "source_code",
  "cross_client",
  "internal_only",
];

export function buildClientSafeStrategyExport(packet: MarketingStrategyPacket): {
  ok: boolean;
  reason?: string;
  body?: Record<string, unknown>;
} {
  const view = composeStrategyView(packet);
  const body = {
    schema: "marketos.marketing_strategy.client_safe_draft.v1",
    strategy_id: view.strategy_id,
    title: view.title,
    draft_only: true,
    executed_campaign: false,
    offer_kind: view.offer_kind,
    surface: view.surface,
    audience: view.audience.map((item) => item.label),
    positioning: view.positioning,
    claims: view.claims.map((claim) => ({
      text: claim.text,
      status: claim.status,
      evidence: claim.evidence_labels,
    })),
    budget_assumptions: view.budgets.map((item) => `${item.name}: ${item.amount_label} (assumption)`),
    next_actions: view.next_actions.map((item) => item.label),
  };
  const encoded = JSON.stringify(body);
  if (OMIT.some((token) => encoded.toLowerCase().includes(token))) {
    return { ok: false, reason: "client_safe_export_rejected" };
  }
  return { ok: true, body };
}
