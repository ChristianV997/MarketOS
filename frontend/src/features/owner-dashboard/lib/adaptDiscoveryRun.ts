/**
 * The one place the provider response is interpreted.
 *
 * Provider: services/opportunity_discovery/service.py, DiscoveryRun.to_dict().
 * Shape read here: { run_version, status, execution_classification,
 * ranked_candidate_ids[], candidates[{candidate_id,name,category,offering_kind,
 * evidence[]}], decisions[{candidate_id, recommendation, readiness, fatal_gates,
 * blockers, evidence_gaps, evidence_classes, metrics, scenarios, experiment,
 * synthesis, sensitivity_drivers}], blockers[], next_best_action, safety{}, fingerprint }.
 *
 * Provider behaviours this mapping preserves rather than papers over:
 *  - ranked_candidate_ids lists ONLY ready, scored candidates; everything else is
 *    "not ranked" (with a reason), never given an invented rank.
 *  - the concept of an evidence gap is `decisions[].evidence_gaps` here, while the
 *    events API's OpportunityScoreView names the same idea `unknowns`/`blockers`.
 *  - money is a decimal string; "unknown"/null are missing, not zero.
 * There is no grade field in the provider response, so none is shown.
 */
import type {
  EconomicsBasis,
  LineState,
  MoneyValue,
  OwnerCandidate,
  OwnerEconomicsLine,
  OwnerEvidenceItem,
  OwnerRun,
  OwnerScenario,
  RatioValue,
  Readiness,
  UnrankedReason,
} from "../contracts/ownerDashboard.ts";
import { parseDecimal } from "./decimal.ts";
import { economicsLineLabel } from "./labels.ts";

export const SUPPORTED_RUN_VERSIONS: ReadonlySet<string> = new Set(["opportunity-discovery-v1"]);

const SAFETY_FLAGS_THAT_MUST_BE_FALSE = [
  "network_calls",
  "provider_calls",
  "credentials_present",
  "orders_created",
  "payments_created",
  "ads_launched",
  "publishing",
  "database_writes",
  "launch_authorized",
] as const;

const RATIO_KEYS: readonly string[] = [
  "contribution_margin",
  "contribution_margin_after_cac",
  "break_even_roas",
  "target_roas",
];

const SCENARIO_ORDER = ["best", "base", "worst"];
const MAX_ID_LENGTH = 200;

export type AdaptErrorCode = "not_an_object" | "unsupported_run_version" | "decisions_missing";
export type AdaptResult = { ok: true; run: OwnerRun } | { ok: false; code: AdaptErrorCode };

type Rec = Record<string, unknown>;

function isRecord(value: unknown): value is Rec {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function textList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim() !== "") : [];
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function unitNumber(value: unknown): number | null {
  const n = finiteNumber(value);
  return n !== null && n >= 0 && n <= 1 ? n : null;
}

export function economicsBasis(provenance: unknown, evidenceState: unknown): EconomicsBasis {
  const p = typeof provenance === "string" ? provenance : "";
  const s = typeof evidenceState === "string" ? evidenceState : "";
  if (s === "assumed" || p === "assumed") return "assumed";
  if (s === "fixture" || p === "fixture") return "fixture";
  if (p === "manual") return "manual";
  if (p === "derived") return "derived";
  if (p === "observed" || s === "observed") return "observed";
  return "unknown";
}

function adaptMoney(value: unknown): MoneyValue {
  if (!isRecord(value)) return { kind: "unavailable" };
  const numeric = parseDecimal(value.amount);
  if (numeric === null) return { kind: "unavailable" };
  return {
    kind: "amount",
    numeric,
    raw: String(value.amount).trim(),
    currency: text(value.currency),
    basis: economicsBasis(value.provenance, value.evidence_state),
  };
}

function adaptRatio(value: unknown): RatioValue {
  const numeric = parseDecimal(value);
  return numeric === null ? { kind: "unavailable" } : { kind: "ratio", numeric, raw: String(value).trim() };
}

/** Lines that are totals built from other lines, so they inherit any missing-input problem. */
const AGGREGATE_LINE_KEYS: readonly string[] = [
  "contribution_before_cac",
  "contribution_after_cac",
  "break_even_cac",
  "target_cac",
  "cash_required_per_order",
];

/** brokerage_fee -> brokerage, affiliate_fee_rate -> affiliate, payment_fee_fixed -> payment. */
function inputStem(name: string): string {
  let stem = name.toLowerCase();
  for (;;) {
    const next = stem.replace(/_(?:fees|fee|rate|fixed)$/, "");
    if (next === stem) return stem;
    stem = next;
  }
}

/**
 * The provider fills inputs it could not find with a zero of unknown basis and lists them in
 * missing_inputs. A zero standing in for a missing input is a placeholder, not a value, and every
 * total computed from it is overstated, so neither is presented as a figure.
 */
function classifyLine(key: string, money: MoneyValue, missingStems: ReadonlySet<string>): { money: MoneyValue; state: LineState } {
  if (AGGREGATE_LINE_KEYS.includes(key)) return { money: { kind: "unavailable" }, state: "depends_on_missing" };
  if (!missingStems.has(inputStem(key))) return { money, state: "ok" };
  if (money.kind === "amount" && money.numeric !== 0 && money.basis !== "unknown") return { money, state: "excludes_missing" };
  return { money: { kind: "unavailable" }, state: "input_missing" };
}

function adaptScenario(name: string, value: unknown): OwnerScenario | null {
  if (!isRecord(value)) return null;
  const providerLabel = text(value.scenario);
  const missingInputs = textList(value.missing_inputs);
  if (value.status === "unavailable") {
    return { name, providerLabel, status: "unavailable", incomplete: false, lines: [], ratios: {}, missingInputs };
  }
  const incomplete = missingInputs.length > 0;
  const missingStems = new Set(missingInputs.map(inputStem));
  const lines: OwnerEconomicsLine[] = [];
  const ratios: Record<string, RatioValue> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (isRecord(entry) && "amount" in entry) {
      const adaptedMoney = adaptMoney(entry);
      const classified = incomplete ? classifyLine(key, adaptedMoney, missingStems) : { money: adaptedMoney, state: "ok" as const };
      lines.push({ key, label: economicsLineLabel(key), money: classified.money, state: classified.state });
    } else if (RATIO_KEYS.includes(key)) {
      ratios[key] = incomplete ? { kind: "unavailable" } : adaptRatio(entry);
    }
  }
  if (lines.length === 0 && Object.keys(ratios).length === 0) {
    return { name, providerLabel, status: "unavailable", incomplete: false, lines: [], ratios: {}, missingInputs };
  }
  return { name, providerLabel, status: "available", incomplete, lines, ratios, missingInputs };
}

function adaptScenarios(value: unknown): OwnerScenario[] {
  if (!isRecord(value)) return [];
  const names = Object.keys(value).sort((a, b) => {
    const ia = SCENARIO_ORDER.indexOf(a);
    const ib = SCENARIO_ORDER.indexOf(b);
    return (ia === -1 ? SCENARIO_ORDER.length : ia) - (ib === -1 ? SCENARIO_ORDER.length : ib);
  });
  const scenarios: OwnerScenario[] = [];
  for (const name of names) {
    const scenario = adaptScenario(name, value[name]);
    if (scenario) scenarios.push(scenario);
  }
  return scenarios;
}

function adaptEvidence(value: unknown): OwnerEvidenceItem[] {
  if (!Array.isArray(value)) return [];
  const items: OwnerEvidenceItem[] = [];
  value.forEach((entry, index) => {
    if (!isRecord(entry)) return;
    items.push({
      id: text(entry.evidence_id) ?? `evidence-${index + 1}`,
      area: text(entry.area),
      status: text(entry.status),
      evidenceClass: text(entry.evidence_class),
      sourceType: text(entry.source_type),
      sourceRef: text(entry.source_ref),
      freshness: text(entry.freshness),
      conflicting: entry.conflicting === true,
    });
  });
  return items;
}

function normalizeReadiness(value: unknown): Readiness {
  return value === "ready" || value === "not_ready" || value === "blocked" ? value : "unknown";
}

function unrankedReason(readiness: Readiness, rank: number | null): UnrankedReason | null {
  if (rank !== null) return null;
  if (readiness === "blocked") return "blocked";
  if (readiness === "not_ready") return "needs_evidence";
  if (readiness === "ready") return "ready_unscored";
  return "not_ranked";
}

interface CandidateInfo {
  name: string | null;
  category: string | null;
  offeringKind: string | null;
  evidence: OwnerEvidenceItem[];
}

function adaptDecision(decision: Rec, id: string, info: CandidateInfo | undefined, rank: number | null): OwnerCandidate {
  const readiness = normalizeReadiness(decision.readiness);
  const metrics = isRecord(decision.metrics) ? decision.metrics : {};
  const synthesis = isRecord(decision.synthesis) ? decision.synthesis : {};
  const experiment = isRecord(decision.experiment) ? decision.experiment : {};
  return {
    candidateId: id,
    name: info?.name ?? id,
    category: info?.category ?? null,
    offeringKind: info?.offeringKind ?? text(metrics.offering_kind),
    rank,
    unrankedReason: unrankedReason(readiness, rank),
    recommendation: text(decision.recommendation),
    readiness,
    rawReadiness: text(decision.readiness),
    synthesisScore: finiteNumber(metrics.synthesis_score),
    synthesisRecommendation: text(synthesis.recommendation),
    evidenceConfidence: unitNumber(metrics.evidence_confidence),
    fatalGates: textList(decision.fatal_gates),
    blockers: textList(decision.blockers),
    evidenceGaps: textList(decision.evidence_gaps),
    evidenceClasses: textList(decision.evidence_classes),
    evidence: info?.evidence ?? [],
    scenarios: adaptScenarios(decision.scenarios),
    economicsStatus: text(metrics.economics_status),
    economicsMissingInputs: textList(metrics.economics_missing_inputs),
    nextEvidence: textList(experiment.required_evidence),
    sensitivityDrivers: textList(decision.sensitivity_drivers),
    providerClaimedExternalAction: experiment.external_action_allowed === true,
  };
}

function checkSafety(value: unknown): { present: boolean; violations: string[] } {
  if (!isRecord(value)) return { present: false, violations: [] };
  const violations: string[] = [];
  if (value.read_only !== true) violations.push("read_only");
  for (const flag of SAFETY_FLAGS_THAT_MUST_BE_FALSE) {
    if (value[flag] !== false) violations.push(flag);
  }
  return { present: true, violations };
}

export function adaptDiscoveryRun(raw: unknown): AdaptResult {
  if (!isRecord(raw)) return { ok: false, code: "not_an_object" };
  const version = text(raw.run_version);
  if (version === null || !SUPPORTED_RUN_VERSIONS.has(version)) return { ok: false, code: "unsupported_run_version" };
  if (!Array.isArray(raw.decisions)) return { ok: false, code: "decisions_missing" };

  const dropped: string[] = [];

  const infoById = new Map<string, CandidateInfo>();
  if (Array.isArray(raw.candidates)) {
    raw.candidates.forEach((entry, index) => {
      const id = isRecord(entry) ? text(entry.candidate_id) : null;
      if (!isRecord(entry) || id === null) {
        dropped.push(`candidates[${index}]: missing candidate_id`);
        return;
      }
      if (infoById.has(id)) return;
      infoById.set(id, {
        name: text(entry.name),
        category: text(entry.category),
        offeringKind: text(entry.offering_kind),
        evidence: adaptEvidence(entry.evidence),
      });
    });
  }

  const decisions = new Map<string, Rec>();
  raw.decisions.forEach((entry, index) => {
    const id = isRecord(entry) ? text(entry.candidate_id) : null;
    if (!isRecord(entry) || id === null || id.length > MAX_ID_LENGTH) {
      dropped.push(`decisions[${index}]: missing or invalid candidate_id`);
      return;
    }
    if (decisions.has(id)) {
      dropped.push(`decisions[${index}]: duplicate candidate_id "${id}"`);
      return;
    }
    decisions.set(id, entry);
  });

  const rankById = new Map<string, number>();
  for (const id of textList(raw.ranked_candidate_ids)) {
    if (!decisions.has(id)) {
      dropped.push(`ranked_candidate_ids: "${id}" has no decision`);
    } else if (!rankById.has(id)) {
      rankById.set(id, rankById.size + 1);
    }
  }

  const candidates = [...decisions].map(([id, decision]) =>
    adaptDecision(decision, id, infoById.get(id), rankById.get(id) ?? null),
  );
  const safety = checkSafety(raw.safety);

  return {
    ok: true,
    run: {
      providerStatus: text(raw.status),
      executionClassification: text(raw.execution_classification),
      nextBestAction: text(raw.next_best_action),
      blockers: textList(raw.blockers),
      fingerprint: text(raw.fingerprint),
      safetyViolations: safety.violations,
      safetyPresent: safety.present,
      candidates,
      dropped,
    },
  };
}
