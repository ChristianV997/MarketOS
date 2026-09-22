import type { MarketingStrategyPacket } from "../../marketing-strategy-workbench/contracts/marketingStrategyPacket.ts";
import { composeStrategyView, type StrategyView } from "../../marketing-strategy-workbench/lib/composeStrategyView.ts";
import { buildClientSafeStrategyExport } from "../../marketing-strategy-workbench/lib/exportClientSafeStrategy.ts";
import {
  PRODUCT_VALIDATION_REPORT_VERSION,
  RESEARCH_TO_DECISION_APPENDIX_VERSION,
} from "../../first-phase-cockpit/contracts/firstPhaseEvidencePacket.ts";

export interface ProvenanceClaim {
  claim_id: string;
  text: string;
  status: StrategyView["claims"][number]["status"];
  evidence_labels: string[];
  provenance: "packet_evidence";
  proof: false;
}

export interface PublicityScenario {
  strategy_id: string;
  title: string;
  draft_only: true;
  executed_campaign: false;
  proof: false;
  banner: string;
  audience: StrategyView["audience"];
  positioning: string;
  messages: StrategyView["messages"];
  claims: ProvenanceClaim[];
  objections: { objection_id: string; text: string; evidence_labels: string[] }[];
  publicity: StrategyView["publicity"];
  pillars: StrategyView["pillars"];
  paid_tests: StrategyView["paid_tests"];
  ugc_briefs: StrategyView["ugc_briefs"];
  calendar: StrategyView["calendar"];
  channels: StrategyView["channels"];
  funnel: { step_id: string; label: string; assumption: true }[];
  kpis: StrategyView["kpis"];
  budgets: StrategyView["budgets"];
  measurement: StrategyView["measurement"];
  decision_rules: { rule_id: string; kind: "kill" | "iterate" | "scale"; text: string; assumption: true }[];
  legal_blockers: { blocker_id: string; domain: "legal" | "privacy"; reason: string }[];
  approvals: { approval_id: string; label: string; granted: false }[];
  research: { ok: false; reason: string } | { ok: true; launch_authorized: false };
  export_ok: boolean;
}

export function readResearchGate(researchRaw: unknown): PublicityScenario["research"] {
  if (!researchRaw || typeof researchRaw !== "object") {
    return { ok: false, reason: "projection_not_object" };
  }
  const packet = researchRaw as {
    report_version?: string;
    appendix?: {
      research_to_decision_version?: string;
      client_safe_projection?: { launch_authorized?: boolean };
    };
  };
  if (packet.report_version !== PRODUCT_VALIDATION_REPORT_VERSION) {
    return { ok: false, reason: "schema_version_unsupported" };
  }
  if (packet.appendix?.research_to_decision_version !== RESEARCH_TO_DECISION_APPENDIX_VERSION) {
    return { ok: false, reason: "schema_version_unsupported" };
  }
  if (packet.appendix?.client_safe_projection?.launch_authorized === true) {
    return { ok: false, reason: "launch_authorized_rejected" };
  }
  return { ok: true, launch_authorized: false };
}

export function composePublicityScenario(
  packet: MarketingStrategyPacket | null,
  researchRaw: unknown = null,
): PublicityScenario {
  const view = composeStrategyView(packet);
  const research = readResearchGate(researchRaw);
  const exported = packet ? buildClientSafeStrategyExport(packet) : { ok: false };
  const claims: ProvenanceClaim[] = view.claims.map((claim) => ({
    ...claim,
    provenance: "packet_evidence",
    proof: false,
  }));
  return {
    strategy_id: view.strategy_id,
    title: view.title,
    draft_only: true,
    executed_campaign: false,
    proof: false,
    banner: `${view.banner} Fixture, manual, stale, and assumption labels are not proof.`,
    audience: view.audience,
    positioning: view.positioning,
    messages: view.messages,
    claims,
    objections: [
      {
        objection_id: "obj-proof",
        text: "A planning recommendation can be mistaken for a live result.",
        evidence_labels: ["Assumption"],
      },
    ],
    publicity: view.publicity,
    pillars: view.pillars,
    paid_tests: view.paid_tests,
    ugc_briefs: view.ugc_briefs,
    calendar: view.calendar,
    channels: view.channels,
    funnel: [
      { step_id: "land-1", label: "Landing page outline is a planning assumption.", assumption: true },
    ],
    kpis: view.kpis,
    budgets: view.budgets,
    measurement: view.measurement,
    decision_rules: [
      { rule_id: "kill-1", kind: "kill", text: "Stop the draft if evidence stays missing.", assumption: true },
      { rule_id: "iter-1", kind: "iterate", text: "Revise copy only after human review.", assumption: true },
      { rule_id: "scale-1", kind: "scale", text: "Scale is not authorized from this surface.", assumption: true },
    ],
    legal_blockers: [
      { blocker_id: "legal-1", domain: "legal", reason: "No external claim may ship without counsel review." },
      { blocker_id: "priv-1", domain: "privacy", reason: "No customer contact list is loaded." },
    ],
    approvals: view.next_actions.map((action) => ({
      approval_id: action.action_id,
      label: action.label,
      granted: false,
    })),
    research: research.ok ? { ok: true, launch_authorized: false } : { ok: false, reason: research.reason },
    export_ok: exported.ok,
  };
}

export function rejectedLaunchProbe(): string {
  const result = readResearchGate({
    report_version: PRODUCT_VALIDATION_REPORT_VERSION,
    appendix: {
      research_to_decision_version: RESEARCH_TO_DECISION_APPENDIX_VERSION,
      client_safe_projection: { launch_authorized: true, candidates: [] },
    },
  });
  return result.ok ? "accepted" : result.reason;
}
