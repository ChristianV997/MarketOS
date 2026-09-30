/**
 * Owner dashboard: model-layer behavior (executes the real adapter, composer and helpers).
 *
 * Evidence level: FIXTURE-TESTED. The provider payload is the output of the real offline
 * services.opportunity_discovery.run_discovery captured in-process (no HTTP, no live API).
 */
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { test } from "node:test";

import { OWNER_DEMO_DISCOVERY_RUN } from "../src/features/owner-dashboard/fixtures/ownerDemoDiscoveryRun.ts";
import { adaptDiscoveryRun, economicsBasis } from "../src/features/owner-dashboard/lib/adaptDiscoveryRun.ts";
import { composeOwnerDashboard, SAVE_TO_PORTFOLIO_DISABLED } from "../src/features/owner-dashboard/lib/composeOwnerDashboard.ts";
import { NOT_AVAILABLE, formatMoney, parseDecimal } from "../src/features/owner-dashboard/lib/decimal.ts";
import { confidenceText, evidenceStatusText, moneyText, ratioText, scoreText } from "../src/features/owner-dashboard/lib/format.ts";
import { loadStateFromQuery, refreshFailedFromQuery } from "../src/features/owner-dashboard/lib/loadState.ts";
import { buildChartRows, composePerformance } from "../src/features/owner-dashboard/lib/performance.ts";
import { nextRowIndex } from "../src/features/owner-dashboard/lib/rowNavigation.ts";
import { fixtureSource } from "../src/features/owner-dashboard/sources/fixtureSource.ts";

const NOW = Date.parse("2026-09-30T12:00:00Z");
const wire = () => structuredClone(OWNER_DEMO_DISCOVERY_RUN);
const decisionOf = (run, id) => run.decisions.find((d) => d?.candidate_id === id);
const adapted = (run = OWNER_DEMO_DISCOVERY_RUN) => {
  const result = adaptDiscoveryRun(run);
  assert.equal(result.ok, true);
  return result.run;
};
const candidateOf = (run, id) => run.candidates.find((c) => c.candidateId === id);
const compose = (run, options = {}) =>
  composeOwnerDashboard({
    load: { status: "success", payload: { run, asOf: options.asOf ?? null, performance: options.performance ?? null } },
    dataMode: options.dataMode ?? "fixture_demo",
    nowMs: options.nowMs ?? NOW,
    refreshFailed: options.refreshFailed,
  });
const noticeIds = (vm) => vm.notices.map((n) => n.id);

// ---------------------------------------------------------------- ranking and identity

test("adapts the real provider run: stable ids, provider order, and only ready candidates ranked", () => {
  const run = adapted();
  assert.deepEqual(
    run.candidates.map((c) => c.candidateId),
    ["desk-lamp-pro", "monitor-riser", "restricted-category", "supplier-claim-only"],
  );
  assert.deepEqual(
    Object.fromEntries(run.candidates.map((c) => [c.candidateId, c.rank])),
    { "desk-lamp-pro": 1, "monitor-riser": null, "restricted-category": null, "supplier-claim-only": null },
  );
  assert.deepEqual(
    Object.fromEntries(run.candidates.map((c) => [c.candidateId, c.unrankedReason])),
    { "desk-lamp-pro": null, "monitor-riser": "needs_evidence", "restricted-category": "blocked", "supplier-claim-only": "blocked" },
  );
  const top = candidateOf(run, "desk-lamp-pro");
  assert.equal(top.name, "Adjustable desk lamp (demo)");
  assert.equal(top.recommendation, "attractive");
  assert.equal(top.readiness, "ready");
});

test("no grade is invented: the provider sends none, so the model has none", () => {
  for (const candidate of adapted().candidates) assert.equal("grade" in candidate, false);
});

test("a provider score does not earn a rank: needs-evidence candidates keep the score but stay unranked", () => {
  const candidate = candidateOf(adapted(), "monitor-riser");
  assert.equal(candidate.synthesisScore, 0.7875);
  assert.equal(candidate.rank, null);
  assert.equal(candidate.readiness, "not_ready");
  assert.equal(candidate.recommendation, "needs_evidence");
});

test("provider order is authoritative: ranks follow ranked_candidate_ids even when scores disagree", () => {
  const run = wire();
  decisionOf(run, "monitor-riser").readiness = "ready";
  run.ranked_candidate_ids = ["monitor-riser", "desk-lamp-pro"]; // monitor-riser has the LOWER score
  const vm = compose(run);
  assert.deepEqual(vm.ranked.map((c) => [c.candidateId, c.rank]), [["monitor-riser", 1], ["desk-lamp-pro", 2]]);
  assert.deepEqual(vm.unranked.map((c) => c.candidateId), ["restricted-category", "supplier-claim-only"]);
  run.ranked_candidate_ids = ["desk-lamp-pro", "monitor-riser"];
  assert.deepEqual(compose(run).ranked.map((c) => c.candidateId), ["desk-lamp-pro", "monitor-riser"]);
});

test("a ready candidate the provider did not rank is reported as ready-but-unscored, never given a rank", () => {
  const run = wire();
  decisionOf(run, "monitor-riser").readiness = "ready";
  const vm = compose(run);
  const candidate = vm.unranked.find((c) => c.candidateId === "monitor-riser");
  assert.equal(candidate.unrankedReason, "ready_unscored");
  assert.equal(vm.summary.readyUnscoredCount, 1);
  assert.equal(vm.summary.researchReadyCount, 2);
  assert.equal(vm.summary.rankedCount, 1);
});

// ---------------------------------------------------------------- evidence gaps and blockers

test("evidence gaps, blockers and fatal gates map from decisions[] exactly once", () => {
  const run = adapted();
  const needs = candidateOf(run, "monitor-riser");
  assert.equal(needs.evidenceGaps.length, 7);
  assert.ok(needs.evidenceGaps.includes("cac"));
  assert.deepEqual(needs.nextEvidence, ["shipping quote", "lane", "delivery promise"]);
  const restricted = candidateOf(run, "restricted-category");
  assert.deepEqual(restricted.fatalGates, ["restricted_or_legal_category", "supply_unproven"]);
  assert.ok(restricted.evidenceGaps.includes("price"));
  assert.deepEqual(candidateOf(run, "supplier-claim-only").fatalGates, ["supplier_claim_not_verification"]);
  assert.equal(candidateOf(run, "desk-lamp-pro").evidenceGaps.length, 0);
});

test("evidence status text reports what the provider said and never claims completeness", () => {
  const run = adapted();
  assert.equal(evidenceStatusText(candidateOf(run, "monitor-riser")), "7 evidence gaps");
  assert.equal(evidenceStatusText(candidateOf(run, "desk-lamp-pro")), "No evidence gaps reported");
  const bare = { ...candidateOf(run, "desk-lamp-pro"), evidence: [], evidenceGaps: [] };
  assert.equal(evidenceStatusText(bare), "No evidence items provided");
});

// ---------------------------------------------------------------- missing versus zero

test("decimal parsing: only well-formed finite decimals parse; missing values are null, never zero", () => {
  const cases = [
    ["945.0000", 945],
    ["0E-8", 0],
    ["6E+1", 60],
    [" 12.50 ", 12.5],
    [".5", 0.5],
    [12, 12],
    [0, 0],
    ["", null],
    ["   ", null],
    ["unknown", null],
    ["NaN", null],
    ["Infinity", null],
    ["1,000", null],
    ["12abc", null],
    [null, null],
    [undefined, null],
    [Number.NaN, null],
    [Number.POSITIVE_INFINITY, null],
    [{}, null],
    [true, null],
  ];
  for (const [input, expected] of cases) assert.equal(parseDecimal(input), expected, `parseDecimal(${JSON.stringify(input)})`);
});

test("an explicit zero assumption stays a labelled zero while unavailable economics stay unavailable", () => {
  const run = adapted();
  const base = candidateOf(run, "desk-lamp-pro").scenarios.find((s) => s.name === "base");
  const brokerage = base.lines.find((l) => l.key === "brokerage");
  assert.deepEqual(
    { kind: brokerage.money.kind, numeric: brokerage.money.numeric, basis: brokerage.money.basis, raw: brokerage.money.raw },
    { kind: "amount", numeric: 0, basis: "assumed", raw: "0" },
  );
  assert.equal(moneyText(brokerage.money), "MXN 0.00");

  const blocked = candidateOf(run, "restricted-category");
  assert.deepEqual(blocked.scenarios.map((s) => [s.name, s.status]), [["best", "unavailable"], ["base", "unavailable"], ["worst", "unavailable"]]);
  assert.deepEqual(blocked.scenarios[1].missingInputs, ["price", "product_cost", "shipping"]);
  assert.equal(moneyText({ kind: "unavailable" }), NOT_AVAILABLE);
  assert.equal(ratioText({ kind: "unavailable" }, "percent"), NOT_AVAILABLE);
  assert.equal(ratioText(undefined, "multiple"), NOT_AVAILABLE);
  assert.equal(scoreText(null), NOT_AVAILABLE);
  assert.equal(confidenceText(null), NOT_AVAILABLE);
  assert.equal(scoreText(0), "0.000", "a real zero score is shown as zero, not as missing");
});

test("money with a non-numeric amount is unavailable rather than zero", () => {
  const run = wire();
  const base = decisionOf(run, "desk-lamp-pro").scenarios.base;
  base.cac.amount = "unknown";
  base.tax.amount = "";
  base.duty.amount = null;
  const scenario = candidateOf(adapted(run), "desk-lamp-pro").scenarios.find((s) => s.name === "base");
  for (const key of ["cac", "tax", "duty"]) {
    assert.deepEqual(scenario.lines.find((l) => l.key === key).money, { kind: "unavailable" }, key);
  }
});

test("placeholder zeros for missing inputs are unavailable, and totals built on them are not shown", () => {
  const run = adapted();
  for (const scenario of candidateOf(run, "monitor-riser").scenarios) {
    assert.equal(scenario.incomplete, true, scenario.name);
    const line = (key) => scenario.lines.find((l) => l.key === key);
    for (const key of ["cac", "brokerage", "domestic_shipping", "international_shipping", "affiliate_fees"]) {
      assert.deepEqual([line(key).money, line(key).state], [{ kind: "unavailable" }, "input_missing"], `${scenario.name}/${key}`);
    }
    for (const key of ["contribution_before_cac", "contribution_after_cac", "break_even_cac", "target_cac", "cash_required_per_order"]) {
      assert.deepEqual([line(key).money, line(key).state], [{ kind: "unavailable" }, "depends_on_missing"], `${scenario.name}/${key}`);
    }
    for (const key of ["payment_fees", "platform_fees"]) {
      assert.equal(line(key).money.kind, "amount", key);
      assert.equal(line(key).state, "excludes_missing", key);
    }
    assert.equal(line("net_sales").state, "ok");
    assert.equal(line("product_cost").money.kind, "amount");
    for (const ratio of Object.values(scenario.ratios)) assert.deepEqual(ratio, { kind: "unavailable" });
  }
  for (const scenario of candidateOf(run, "desk-lamp-pro").scenarios) {
    assert.equal(scenario.incomplete, false);
    assert.ok(scenario.lines.every((l) => l.state === "ok"));
    const rawScenario = decisionOf(OWNER_DEMO_DISCOVERY_RUN, "desk-lamp-pro").scenarios[scenario.name];
    for (const [key, ratio] of Object.entries(scenario.ratios)) {
      const expected = parseDecimal(rawScenario[key]) === null ? "unavailable" : "ratio";
      assert.equal(ratio.kind, expected, `${scenario.name}/${key}: unavailable exactly when the provider value is not a number`);
    }
  }
  const worst = candidateOf(run, "desk-lamp-pro").scenarios.find((s) => s.name === "worst");
  assert.deepEqual(worst.ratios.target_roas, { kind: "unavailable" }, "the provider's unknown target ROAS is not shown as a number");
});

test("missing-input matching copes with the provider's differing names, and leaves unrelated lines alone", () => {
  const money = (amount, provenance, state) => ({ amount, currency: "MXN", provenance, evidence_state: state });
  const run = wire();
  decisionOf(run, "desk-lamp-pro").scenarios = {
    base: {
      scenario: "base",
      currency: "MXN",
      missing_inputs: ["brokerage_fee", "affiliate_fee_rate", "payment_fee_fixed"],
      brokerage: money("0", "assumed", "unknown"),
      affiliate_fees: money("0.0000", "derived", "observed"),
      payment_fees: money("27.0000", "derived", "observed"),
      tax: money("144.0000", "derived", "observed"),
      contribution_margin: "0.5",
    },
  };
  const base = candidateOf(adapted(run), "desk-lamp-pro").scenarios[0];
  const state = (key) => base.lines.find((l) => l.key === key).state;
  assert.equal(state("brokerage"), "input_missing");
  assert.equal(state("affiliate_fees"), "input_missing", "a derived zero from a missing rate is still a placeholder");
  assert.equal(state("payment_fees"), "excludes_missing");
  assert.equal(state("tax"), "ok");
  assert.deepEqual(base.ratios.contribution_margin, { kind: "unavailable" });
  assert.equal(moneyText(base.lines.find((l) => l.key === "brokerage").money), NOT_AVAILABLE);
});

test("economics basis follows provenance and evidence state without upgrading anything", () => {
  assert.equal(economicsBasis("manual", "observed"), "manual");
  assert.equal(economicsBasis("derived", "observed"), "derived");
  assert.equal(economicsBasis("assumed", "assumed"), "assumed");
  assert.equal(economicsBasis("derived", "assumed"), "assumed", "a derived value built on assumptions is still an assumption");
  assert.equal(economicsBasis("manual", "assumed"), "assumed");
  assert.equal(economicsBasis("fixture", "unknown"), "fixture");
  assert.equal(economicsBasis(undefined, undefined), "unknown");
  assert.equal(economicsBasis("derived", "unknown"), "derived");

  const base = candidateOf(adapted(), "desk-lamp-pro").scenarios.find((s) => s.name === "base");
  const basis = (key) => base.lines.find((l) => l.key === key).money.basis;
  assert.equal(basis("cac"), "assumed");
  assert.equal(basis("product_cost"), "manual");
  assert.equal(basis("net_sales"), "derived");
});

test("ratios come through as provided and format without recalculation", () => {
  const base = candidateOf(adapted(), "desk-lamp-pro").scenarios.find((s) => s.name === "base");
  assert.equal(ratioText(base.ratios.contribution_margin_after_cac, "percent"), "8.3%");
  assert.equal(ratioText(base.ratios.break_even_roas, "multiple"), "4.62×");
  assert.equal(base.ratios.target_roas.raw, "6E+1");
  assert.equal(ratioText(base.ratios.target_roas, "multiple"), "60.00×");
  assert.equal(formatMoney(1234.5, "mxn"), "MXN 1,234.50");
  assert.equal(formatMoney(5, null), "5.00");
  assert.equal(formatMoney(5, "not-a-code"), "5.00");
});

test("out-of-range or non-finite provider metrics become missing, not clamped or zeroed", () => {
  const run = wire();
  const metrics = decisionOf(run, "desk-lamp-pro").metrics;
  metrics.evidence_confidence = 1.7;
  metrics.synthesis_score = "0.83";
  const candidate = candidateOf(adapted(run), "desk-lamp-pro");
  assert.equal(candidate.evidenceConfidence, null);
  assert.equal(candidate.synthesisScore, null);
  assert.equal(candidateOf(adapted(), "desk-lamp-pro").evidenceConfidence, 0.6667);
});

// ---------------------------------------------------------------- research-ready vs launch authorization

test("the readiness summary separates research-ready from launch authorization", () => {
  const vm = compose(OWNER_DEMO_DISCOVERY_RUN);
  assert.equal(vm.status, "ready");
  assert.deepEqual(vm.summary, {
    total: 4,
    rankedCount: 1,
    researchReadyCount: 1,
    needsEvidenceCount: 1,
    blockedCount: 2,
    readyUnscoredCount: 0,
    launchAuthorized: false,
  });
  assert.equal(vm.saveToPortfolio.enabled, false);
  assert.match(vm.saveToPortfolio.reason, /Not connected/);
  assert.equal(vm.saveToPortfolio, SAVE_TO_PORTFOLIO_DISABLED);
});

test("a provider claiming launch or external-action authority is flagged and ignored", () => {
  const launch = wire();
  launch.safety.launch_authorized = true;
  const vm = compose(launch);
  assert.equal(vm.summary.launchAuthorized, false);
  assert.equal(vm.notices[0].id, "provider_integrity");
  assert.equal(vm.notices[0].tone, "danger");
  assert.match(vm.notices[0].detail, /launch_authorized/);

  const readOnly = wire();
  readOnly.safety.read_only = false;
  readOnly.safety.publishing = true;
  assert.match(compose(readOnly).notices[0].detail, /read_only, publishing/);

  const missing = wire();
  delete missing.safety;
  assert.match(compose(missing).notices[0].detail, /no safety flags/);

  const external = wire();
  decisionOf(external, "monitor-riser").experiment.external_action_allowed = true;
  const externalVm = compose(external);
  assert.match(externalVm.notices[0].detail, /monitor-riser/);
  assert.equal(externalVm.unranked.find((c) => c.candidateId === "monitor-riser").providerClaimedExternalAction, true);
  assert.equal(externalVm.summary.launchAuthorized, false);

  assert.deepEqual(noticeIds(compose(OWNER_DEMO_DISCOVERY_RUN)), ["demo_data"], "an honest run raises no integrity notice");
});

// ---------------------------------------------------------------- states

test("loading and unavailable states carry no data and keep the demo notice", () => {
  const loading = composeOwnerDashboard({ load: { status: "loading" }, dataMode: "fixture_demo", nowMs: NOW });
  assert.equal(loading.status, "loading");
  assert.deepEqual(noticeIds(loading), ["demo_data"]);
  assert.equal(loading.summary, null);
  assert.deepEqual([loading.ranked, loading.unranked], [[], []]);

  const down = composeOwnerDashboard({ load: { status: "error", code: "source_unavailable" }, dataMode: "fixture_demo", nowMs: NOW });
  assert.equal(down.status, "unavailable");
  assert.equal(down.error.code, "source_unavailable");
  assert.match(down.error.message, /Nothing below is shown as live data/);
  assert.deepEqual([down.ranked, down.unranked, down.run, down.summary], [[], [], null, null]);
  assert.equal(down.performance.status, "unavailable");
});

test("malformed provider responses become a recoverable malformed state, never a crash or guessed data", () => {
  const cases = [
    [null, "not_an_object"],
    ["text", "not_an_object"],
    [[], "not_an_object"],
    [{}, "unsupported_run_version"],
    [{ run_version: "opportunity-discovery-v9", decisions: [] }, "unsupported_run_version"],
    [{ run_version: "opportunity-discovery-v1" }, "decisions_missing"],
    [{ run_version: "opportunity-discovery-v1", decisions: {} }, "decisions_missing"],
  ];
  for (const [payload, code] of cases) {
    const vm = compose(payload);
    assert.equal(vm.status, "malformed", JSON.stringify(payload));
    assert.equal(vm.error.code, code);
    assert.deepEqual(vm.ranked, []);
  }
});

test("an empty run is an empty state and keeps the provider's next step", () => {
  const run = wire();
  run.decisions = [];
  run.candidates = [];
  run.ranked_candidate_ids = [];
  run.status = "unavailable";
  run.next_best_action = "supply sanitized candidates";
  const vm = compose(run);
  assert.equal(vm.status, "empty");
  assert.equal(vm.run.nextBestAction, "supply sanitized candidates");
  assert.equal(vm.summary.total, 0);
});

test("unreadable provider records are skipped and reported as a partial result", () => {
  const run = wire();
  run.decisions.unshift(null, { candidate_id: "" }, { recommendation: "x" });
  run.decisions.push(structuredClone(decisionOf(run, "monitor-riser")));
  run.ranked_candidate_ids.push("ghost");
  run.candidates.push(null);
  const vm = compose(run);
  assert.equal(vm.status, "ready");
  assert.equal(vm.ranked.length + vm.unranked.length, 4, "readable candidates are still shown");
  const notice = vm.notices.find((n) => n.id === "partial_records");
  assert.equal(notice.tone, "warning");
  assert.match(notice.detail, /6 records were unreadable/);
  assert.match(notice.detail, /incomplete/);
});

test("duplicate candidate ids keep the first record so identity stays stable", () => {
  const run = wire();
  const duplicate = structuredClone(decisionOf(run, "desk-lamp-pro"));
  duplicate.recommendation = "blocked";
  run.decisions.push(duplicate);
  assert.equal(candidateOf(adapted(run), "desk-lamp-pro").recommendation, "attractive");
});

test("freshness: stale, unreadable, and unknown timestamps are reported honestly", () => {
  assert.deepEqual(noticeIds(compose(OWNER_DEMO_DISCOVERY_RUN, { asOf: "2026-09-30T11:00:00Z" })), ["demo_data"]);

  const stale = compose(OWNER_DEMO_DISCOVERY_RUN, { asOf: "2026-09-27T12:00:00Z" });
  const staleNotice = stale.notices.find((n) => n.id === "stale");
  assert.equal(staleNotice.tone, "warning");
  assert.match(staleNotice.detail, /older than 24 hours/);

  assert.ok(noticeIds(compose(OWNER_DEMO_DISCOVERY_RUN, { asOf: "not-a-date" })).includes("freshness_unknown"));

  assert.deepEqual(noticeIds(compose(OWNER_DEMO_DISCOVERY_RUN)), ["demo_data"], "demo data needs no freshness notice");
  const live = compose(OWNER_DEMO_DISCOVERY_RUN, { dataMode: "live_readonly" });
  assert.deepEqual(noticeIds(live), ["freshness_unknown"], "non-demo data without a timestamp is flagged, and is not labelled demo");
});

test("stale, future-dated or unknown-age evidence raises a warning with a count", () => {
  const run = wire();
  const items = run.candidates[0].evidence;
  items[0].freshness = "stale";
  items[1].freshness = "future";
  const notice = compose(run).notices.find((n) => n.id === "evidence_freshness");
  assert.equal(notice.tone, "warning");
  assert.match(notice.detail, /2 evidence items are/);
});

test("a failed refresh keeps the last loaded data and says so", () => {
  const vm = compose(OWNER_DEMO_DISCOVERY_RUN, { refreshFailed: true });
  assert.equal(vm.status, "ready");
  assert.equal(vm.notices.find((n) => n.title === "Showing the last loaded data").tone, "warning");
});

test("notices are ordered danger, then warning, then info", () => {
  const run = wire();
  run.safety.launch_authorized = true;
  run.candidates[0].evidence[0].freshness = "stale";
  const vm = compose(run, { asOf: "2026-09-27T12:00:00Z" });
  const tones = vm.notices.map((n) => n.tone);
  assert.deepEqual(tones, [...tones].sort((a, b) => ({ danger: 0, warning: 1, info: 2 })[a] - ({ danger: 0, warning: 1, info: 2 })[b]));
  assert.equal(tones[0], "danger");
  assert.equal(tones.at(-1), "info");
});

test("query snapshot maps to a load state: data wins over an error", () => {
  const payload = { run: {}, asOf: null, performance: null };
  assert.deepEqual(loadStateFromQuery({ data: undefined, isError: false }), { status: "loading" });
  assert.deepEqual(loadStateFromQuery({ data: undefined, isError: true }), { status: "error", code: "source_unavailable" });
  assert.deepEqual(loadStateFromQuery({ data: payload, isError: false }), { status: "success", payload });
  assert.deepEqual(loadStateFromQuery({ data: payload, isError: true }), { status: "success", payload });
  assert.equal(refreshFailedFromQuery({ data: payload, isError: true }), true);
  assert.equal(refreshFailedFromQuery({ data: undefined, isError: true }), false);
  assert.equal(refreshFailedFromQuery({ data: payload, isError: false }), false);
});

// ---------------------------------------------------------------- performance

test("performance is unavailable, not zero, when there are no observed values", () => {
  for (const input of [null, [], [{ id: "x", label: "X", unit: "count", provenance: "observed", points: [] }]]) {
    const model = composePerformance(input);
    assert.equal(model.status, "unavailable");
    assert.ok(model.reason.length > 0);
  }
  const allMissing = composePerformance([
    { id: "x", label: "X", unit: "count", provenance: "observed", points: [{ periodLabel: "W1", value: null }, { periodLabel: "W2", value: Number.NaN }] },
  ]);
  assert.equal(allMissing.status, "unavailable");
});

test("fixture performance is labelled as demo, and missing periods stay null gaps", async () => {
  const { performance } = await fixtureSource.load();
  const model = composePerformance(performance);
  assert.equal(model.status, "fixture_demo");
  assert.equal(model.missingPoints, 2);
  const rows = buildChartRows(model.series);
  assert.equal(rows.length, 8);
  assert.deepEqual(rows.filter((r) => r.orders_per_week === null).map((r) => r.period), ["Wk 4", "Wk 7"]);
  assert.equal(rows.some((r) => r.orders_per_week === 0), false, "no missing value was turned into zero");
});

test("performance is only called observed when every series is observed", () => {
  const observed = { id: "o", label: "O", unit: "count", provenance: "observed", points: [{ periodLabel: "W1", value: 3 }] };
  const fixture = { id: "f", label: "F", unit: "count", provenance: "fixture", points: [{ periodLabel: "W1", value: 9 }] };
  assert.equal(composePerformance([observed]).status, "observed");
  assert.equal(composePerformance([observed, fixture]).status, "fixture_demo");
  assert.equal(composePerformance([fixture]).status, "fixture_demo");
  assert.equal(composePerformance([{ ...observed, points: [{ periodLabel: "W1", value: 0 }] }]).status, "observed", "a real zero is a value");
});

// ---------------------------------------------------------------- source, navigation, safety

test("the fixture source is labelled demo, carries no timestamp, and makes no network request", async () => {
  const realFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = () => {
    calls += 1;
    throw new Error("network is forbidden in the fixture source");
  };
  try {
    const payload = await fixtureSource.load();
    assert.equal(fixtureSource.dataMode, "fixture_demo");
    assert.equal(fixtureSource.id, "fixture-demo");
    assert.equal(payload.asOf, null);
    assert.equal(payload.run, OWNER_DEMO_DISCOVERY_RUN);
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal(calls, 0);
});

test("row navigation clamps at the ends and ignores other keys", () => {
  assert.equal(nextRowIndex(0, "ArrowDown", 4), 1);
  assert.equal(nextRowIndex(3, "ArrowDown", 4), 3);
  assert.equal(nextRowIndex(0, "ArrowUp", 4), 0);
  assert.equal(nextRowIndex(2, "ArrowUp", 4), 1);
  assert.equal(nextRowIndex(2, "Home", 4), 0);
  assert.equal(nextRowIndex(1, "End", 4), 3);
  assert.equal(nextRowIndex(1, "Enter", 4), null);
  assert.equal(nextRowIndex(0, "ArrowDown", 0), null);
});

test("owner dashboard sources hold no network, credential, execution-authority, or money-math code", async () => {
  const root = new URL("../src/features/owner-dashboard/", import.meta.url);
  const files = [];
  async function collect(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const child = new URL(entry.name + (entry.isDirectory() ? "/" : ""), dir);
      if (entry.isDirectory()) await collect(child);
      else if (/\.(ts|tsx)$/.test(entry.name)) files.push(child);
    }
  }
  await collect(root);
  files.push(new URL("../src/pages/OwnerDashboard.tsx", import.meta.url));
  assert.ok(files.length >= 15);

  for (const file of files) {
    const source = await readFile(file, "utf8");
    const label = file.pathname.split("/owner-dashboard/").pop();
    assert.doesNotMatch(source, /\bfetch\s*\(|XMLHttpRequest|new WebSocket|sendBeacon|axios/, `${label}: network call`);
    assert.doesNotMatch(
      source,
      /["'`]Authorization["'`]|Bearer\s|api[_-]?key|\bcredentials\s*:|localStorage|sessionStorage|document\.cookie/i,
      `${label}: credential or storage use`,
    );
    assert.doesNotMatch(source, /calculate_unit_economics|calculate_service_economics|SHOPIFY_ADMIN_TOKEN|STRIPE_SECRET_KEY/, `${label}: execution authority`);
    if (label.startsWith("fixtures/")) continue;
    assert.doesNotMatch(
      source,
      /\b(?:const|let|function)\s+(?:break_even_roas|break_even_cac|contribution_before_cac|contribution_after_cac|refund_lag_exposure)\b/,
      `${label}: computes a financial value`,
    );
    assert.doesNotMatch(source, /\.numeric\s*[-+*/%]\s*[\w(]|[\w)]\s*[-+*/%]\s*[\w.]+\.numeric\b/, `${label}: arithmetic on a money value`);
  }
});
