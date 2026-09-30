/**
 * Owner dashboard: rendered-component behavior.
 *
 * Renders the real React components (react-dom/server) through tests/helpers/tsx-hooks.mjs and queries
 * the output by role and accessible name, the way a user or screen reader perceives it.
 *
 * Evidence level: FIXTURE-TESTED. No HTTP request is made and no live API is involved.
 * Not covered here: pointer/keyboard event handling in a real browser, and chart pixels.
 */
import "./helpers/register-tsx.mjs";

import assert from "node:assert/strict";
import { test } from "node:test";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  accessibleName,
  cellsOf,
  definitionOf,
  getByRole,
  hasText,
  parseHtml,
  queryAllByRole,
  queryByRole,
  rowsOf,
  textContent,
} from "./helpers/htmlTree.mjs";

const { OwnerDashboardView } = await import("../src/features/owner-dashboard/components/OwnerDashboardView.tsx");
const { composeOwnerDashboard } = await import("../src/features/owner-dashboard/lib/composeOwnerDashboard.ts");
const { fixtureSource } = await import("../src/features/owner-dashboard/sources/fixtureSource.ts");
const { OWNER_DEMO_DISCOVERY_RUN } = await import("../src/features/owner-dashboard/fixtures/ownerDemoDiscoveryRun.ts");
const { useOwnerDashboard } = await import("../src/features/owner-dashboard/hooks/useOwnerDashboard.ts");
const { default: OwnerDashboardPage } = await import("../src/pages/OwnerDashboard.tsx");

const NOW = Date.parse("2026-09-30T12:00:00Z");
const demoPayload = await fixtureSource.load();
const compose = (load, options = {}) =>
  composeOwnerDashboard({ load, dataMode: options.dataMode ?? "fixture_demo", nowMs: NOW, refreshFailed: options.refreshFailed });
const readyModel = (payload = demoPayload, options) => compose({ status: "success", payload }, options);
const render = (viewModel, props = {}) =>
  parseHtml(
    renderToStaticMarkup(
      createElement(OwnerDashboardView, { viewModel, selectedId: null, onSelect() {}, onRetry() {}, ...props }),
    ),
  );
const withRun = (mutate, extra = {}) => {
  const run = structuredClone(OWNER_DEMO_DISCOVERY_RUN);
  mutate(run);
  return { ...demoPayload, run, ...extra };
};
const rowWithHeader = (table, name) => rowsOf(table).find((row) => cellsOf(row)[0]?.startsWith(name));

// ---------------------------------------------------------------- ready overview

test("ready: the page names itself, says it is demo data, and keeps advice separate from authority", () => {
  const tree = render(readyModel());
  assert.ok(getByRole(tree, "heading", { level: 1, name: "Owner cockpit" }));
  const demo = getByRole(tree, "status", { name: /^Demo data\./ });
  assert.match(textContent(demo), /not your portfolio, not live market data, and not connected to Shopify or any account/);
  assert.match(textContent(tree), /Shopify remains the commerce execution authority/);
  assert.match(textContent(tree), /everything here is advisory/);
});

test("ready: research-ready is shown separately from launch authorization, which is never granted", () => {
  const tree = render(readyModel());
  assert.deepEqual(definitionOf(tree, "Launch authorization"), ["Not authorized", "this page cannot grant it"]);
  assert.deepEqual(definitionOf(tree, "Research-ready"), ["1", "evidence checks passed for review"]);
  assert.deepEqual(definitionOf(tree, "Ranked by provider"), ["1", "of 4 candidates"]);
  assert.deepEqual(definitionOf(tree, "Needs evidence"), ["1"]);
  assert.deepEqual(definitionOf(tree, "Blocked"), ["2"]);
  assert.match(textContent(tree), /Research-ready is not launch authorization\./);
});

test("ready: the ranked table shows stable identity, rank, recommendation, score, confidence and evidence status", () => {
  const tree = render(readyModel());
  const table = getByRole(tree, "table", { name: /Ranked opportunities in the provider's order/ });
  const rows = rowsOf(table);
  assert.equal(rows.length, 1);
  const cells = cellsOf(rows[0]);
  assert.equal(cells[0], "#1");
  assert.match(cells[1], /^Adjustable desk lamp \(demo\)desk-lamp-pro · home$/);
  assert.equal(cells[2], "Attractive");
  assert.equal(cells[3], "0.831");
  assert.equal(cells[4], "67%");
  assert.match(cells[5], /^No evidence gaps reported/);
  assert.deepEqual(
    queryAllByRole(table, "columnheader").map(textContent),
    ["Rank", "Opportunity", "Recommendation", "Provider score", "Evidence confidence", "Evidence status"],
  );
  assert.match(textContent(tree), /never re-sorts or re-scores them/);
});

test("ready: candidates without a rank are listed apart, with the provider's reason and no invented rank or zero", () => {
  const tree = render(readyModel());
  const table = getByRole(tree, "table", { name: /did not rank, with the reason/ });
  const rows = rowsOf(table);
  assert.equal(rows.length, 3);
  const monitor = cellsOf(rowWithHeader(table, "Monitor riser (demo)"));
  assert.equal(monitor[1], "Needs evidence");
  assert.match(monitor[3], /^0\.78[78]$/, "the score is shown, but it does not earn a rank");
  assert.match(monitor[4], /^7 evidence gaps/);
  for (const name of ["Restricted", "Claim only"]) {
    const cells = cellsOf(rowWithHeader(table, name));
    assert.equal(cells[1], "Blocked by a fatal gate");
    assert.equal(cells[2], "Blocked");
    assert.equal(cells[3], "Not available", "a missing score is not shown as 0.000");
  }
  for (const row of rows) assert.doesNotMatch(cellsOf(row).join("|"), /#\d/, "unranked rows carry no rank number");
});

test("ready: selection is exposed as a pressed button, and the first candidate is selected by default", () => {
  const defaults = render(readyModel());
  assert.equal(getByRole(defaults, "button", { name: "Adjustable desk lamp (demo)" }).attrs["aria-pressed"], "true");
  assert.equal(getByRole(defaults, "button", { name: "Monitor riser (demo)" }).attrs["aria-pressed"], "false");
  assert.ok(getByRole(defaults, "heading", { level: 2, name: "Adjustable desk lamp (demo)" }));

  const picked = render(readyModel(), { selectedId: "monitor-riser" });
  assert.equal(getByRole(picked, "button", { name: "Monitor riser (demo)" }).attrs["aria-pressed"], "true");
  assert.equal(getByRole(picked, "button", { name: "Adjustable desk lamp (demo)" }).attrs["aria-pressed"], "false");
  assert.ok(getByRole(picked, "heading", { level: 2, name: "Monitor riser (demo)" }));

  const unknown = render(readyModel(), { selectedId: "no-such-candidate" });
  assert.ok(getByRole(unknown, "heading", { level: 2, name: "Adjustable desk lamp (demo)" }), "an unknown selection falls back to the first candidate");
});

test("ready: keyboard users get a skip link, labelled scroll regions, and every row is reachable by button", () => {
  const tree = render(readyModel());
  assert.equal(getByRole(tree, "link", { name: "Skip to selected opportunity details" }).attrs.href, "#owner-candidate-detail");
  assert.ok(getByRole(tree, "region", { name: "Ranked opportunities table" }).attrs.tabindex === "0");
  assert.ok(getByRole(tree, "region", { name: "Not ranked opportunities table" }).attrs.tabindex === "0");
  const buttons = queryAllByRole(tree, "button", { name: /\(demo\)|Restricted|Claim only/ });
  assert.equal(buttons.length, 4);
  assert.deepEqual(buttons.map((b) => b.attrs["data-candidate-id"]), ["desk-lamp-pro", "monitor-riser", "restricted-category", "supplier-claim-only"]);
});

// ---------------------------------------------------------------- candidate detail

test("detail (ranked): recommendation is advisory, and the save action is disabled with an honest reason", () => {
  const tree = render(readyModel());
  assert.match(textContent(getByRole(tree, "region", { name: "Adjustable desk lamp (demo)" })), /Advisory only\. “Attractive” is a research recommendation, not launch authorization/);
  const save = getByRole(tree, "button", { name: "Save to portfolio (not connected)" });
  assert.ok("disabled" in save.attrs, "the save button is really disabled");
  const reason = textContent(findById(tree, save.attrs["aria-describedby"]));
  assert.match(reason, /Not connected: no authorized portfolio backend exists yet/);
});

function findById(node, id) {
  if (node.attrs?.id === id) return node;
  for (const child of node.children ?? []) {
    const found = child.text === undefined ? findById(child, id) : null;
    if (found) return found;
  }
  return null;
}

test("detail (ranked): economics are labelled planning estimates, and every line says how it is grounded", () => {
  const tree = render(readyModel());
  assert.match(textContent(tree), /Per-order figures the economics kernel derived from supplied inputs and assumptions\. They are not measured results/);
  const scenarios = queryAllByRole(tree, "radio");
  assert.deepEqual(scenarios.map(accessibleName), ["Best case", "Base case", "Worst case"]);
  assert.deepEqual(scenarios.map((r) => "checked" in r.attrs), [false, true, false], "base case is the default");

  const table = getByRole(tree, "table", { name: /Per-order economics line items for the Base case scenario/ });
  const line = (name) => cellsOf(rowWithHeader(table, name));
  assert.deepEqual(line("Customer acquisition cost (CAC)"), ["Customer acquisition cost (CAC)", "MXN 120.00", "Assumption"]);
  assert.deepEqual(line("Product cost"), ["Product cost", "MXN 300.00", "Manual input"]);
  assert.deepEqual(line("Net sales"), ["Net sales", "MXN 900.00", "Derived"]);
  assert.deepEqual(line("Brokerage"), ["Brokerage", "MXN 0.00", "Assumption"], "an explicit zero assumption stays a labelled zero");
  assert.deepEqual(definitionOf(tree, "Contribution after CAC"), ["MXN 75.00", "Derived"]);
  assert.deepEqual(definitionOf(tree, "Contribution margin after CAC"), ["8.3%"]);
  assert.deepEqual(definitionOf(tree, "Break-even ROAS"), ["4.62×"]);
  assert.equal(queryByRole(tree, "note"), null, "a complete scenario raises no missing-input note");
});

test("detail (needs evidence): missing inputs are unavailable, not zero, and totals built on them are withheld", () => {
  const tree = render(readyModel(), { selectedId: "monitor-riser" });
  const note = getByRole(tree, "note");
  assert.match(textContent(note), /Incomplete inputs\./);
  assert.match(textContent(note), /Domestic shipping, International shipping, Brokerage fee, Payment fee fixed, Platform fee fixed, Cac, Affiliate fee rate/);
  assert.match(textContent(note), /a zero the provider fills in for a missing input is a placeholder, not a value/);

  const table = getByRole(tree, "table", { name: /Base case scenario/ });
  for (const name of ["Customer acquisition cost (CAC)", "Brokerage", "Domestic shipping", "International shipping", "Affiliate fees"]) {
    assert.deepEqual(cellsOf(rowWithHeader(table, name)).slice(1), ["Not available", "Input missing"], name);
  }
  for (const name of ["Contribution before CAC", "Contribution after CAC", "Break-even CAC", "Target CAC", "Cash required per order"]) {
    assert.deepEqual(cellsOf(rowWithHeader(table, name)).slice(1), ["Not available", "Depends on missing inputs"], name);
  }
  for (const name of ["Payment fees", "Platform fees"]) {
    const cells = cellsOf(rowWithHeader(table, name));
    assert.match(cells[1], /^MXN \d+\.\d{2}$/);
    assert.match(cells[2], /Excludes a missing input/);
  }
  assert.deepEqual(cellsOf(rowWithHeader(table, "Net sales")).slice(1), ["MXN 900.00", "Derived"]);
  assert.deepEqual(definitionOf(tree, "Contribution after CAC"), ["Not available", "Depends on missing inputs"]);
  assert.deepEqual(definitionOf(tree, "Contribution margin after CAC"), ["Not available", "Depends on missing inputs"]);
  assert.deepEqual(definitionOf(tree, "Break-even ROAS"), ["Not available", "Depends on missing inputs"]);
  const zeroRows = rowsOf(table).filter((row) => cellsOf(row)[1] === "MXN 0.00").map((row) => cellsOf(row)[0]);
  assert.deepEqual(
    zeroRows,
    ["Duty", "Marketplace fees", "Chargeback reserve", "FX reserve", "Refund-lag exposure"],
    "only lines whose inputs were actually supplied as zero still show zero; no missing-input placeholder does",
  );
  for (const name of zeroRows) assert.equal(cellsOf(rowWithHeader(table, name))[2], "Derived", name);
});

test("detail (needs evidence): the reasons, next evidence, and the synthesis-versus-evidence conflict are explained", () => {
  const tree = render(readyModel(), { selectedId: "monitor-riser" });
  assert.ok(getByRole(tree, "heading", { level: 4, name: /^Evidence gaps\s*7$/ }));
  assert.match(textContent(tree), /Affiliate fee rate\s*affiliate_fee_rate/);
  assert.match(textContent(tree), /opportunity-synthesis component suggests “Advance to launch draft”, but this candidate is not research-ready, so the evidence status above takes precedence/);
  const next = getByRole(tree, "heading", { level: 3, name: "Next evidence to collect" });
  assert.ok(next);
  for (const item of ["Shipping quote", "Lane", "Delivery promise"]) assert.ok(hasText(tree, item), item);
  assert.match(textContent(tree), /No external action is authorized by this list\./);
});

test("detail (blocked): fatal gates lead, and unavailable economics say why instead of showing numbers", () => {
  const tree = render(readyModel(), { selectedId: "restricted-category" });
  assert.ok(getByRole(tree, "heading", { level: 4, name: /^Fatal gates\s*2$/ }));
  assert.match(textContent(tree), /Restricted or legal category\s*restricted_or_legal_category/);
  assert.match(textContent(tree), /Not available\. The provider could not calculate this scenario, so no figure is shown, not even zero\./);
  assert.match(textContent(tree), /Missing inputs: Price, Product cost, Shipping\./);
  assert.equal(queryByRole(tree, "table", { name: /economics line items/ }), null, "no line-item table is invented");
  assert.deepEqual(queryAllByRole(tree, "radio").map(accessibleName), ["Best case (not available)", "Base case (not available)", "Worst case (not available)"]);
});

test("detail: evidence provenance lists area, status, class and freshness, and admits when there is none", () => {
  const tree = render(readyModel());
  const table = getByRole(tree, "table", { name: /Evidence items behind this candidate/ });
  const rows = rowsOf(table).map(cellsOf);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows[0].slice(0, 4), ["Demand", "Observed fact", "Fixture", "Current"]);
  assert.match(rows[0][4], /^fixture:\/\/market\/desk-lamp-pro$/);
  const bare = withRun((run) => {
    run.candidates[0].evidence = [];
  });
  assert.match(textContent(render(readyModel(bare))), /The provider supplied no evidence items for this candidate\./);
});

// ---------------------------------------------------------------- states

test("loading: a polite busy status, no data, and the demo notice is already visible", () => {
  const tree = render(compose({ status: "loading" }));
  const status = getByRole(tree, "status", { name: /Loading owner dashboard…/ });
  assert.equal(status.attrs["aria-busy"], "true");
  assert.equal(status.attrs["aria-live"], "polite");
  assert.ok(getByRole(tree, "status", { name: /^Demo data\./ }));
  assert.equal(queryByRole(tree, "table"), null);
  assert.equal(queryByRole(tree, "button"), null);
});

test("unavailable: a recoverable alert with a working retry, no data, and nothing presented as live", () => {
  const tree = render(compose({ status: "error", code: "source_unavailable" }));
  const alert = getByRole(tree, "alert", { name: /Owner dashboard unavailable/ });
  assert.match(textContent(alert), /Nothing below is shown as live data/);
  assert.match(textContent(alert), /Reason code: source_unavailable/);
  const retry = getByRole(alert, "button", { name: "Try again" });
  assert.equal("disabled" in retry.attrs, false);
  assert.equal(queryByRole(tree, "table"), null);
  assert.equal(hasText(tree, "Adjustable desk lamp"), false, "no data is shown while the source is down");
  assert.equal(hasText(tree, "Portfolio readiness"), false);

  const retrying = render(compose({ status: "error" }), { isRetrying: true });
  const busy = getByRole(retrying, "button", { name: "Trying again…" });
  assert.ok("disabled" in busy.attrs, "retry cannot be double-submitted");
});

test("malformed: the reason is named and retry is offered, without exposing provider internals", () => {
  const tree = render(compose({ status: "success", payload: { ...demoPayload, run: { run_version: "opportunity-discovery-v9", decisions: [] } } }));
  const alert = getByRole(tree, "alert", { name: /The discovery response could not be read/ });
  assert.match(textContent(alert), /unsupported_run_version/);
  assert.match(textContent(alert), /does not support/);
  assert.ok(getByRole(alert, "button", { name: "Try again" }));
  assert.equal(queryByRole(tree, "table"), null);
});

test("empty: an honest empty state that adds no fake action and keeps the provider's next step", () => {
  const payload = withRun((run) => {
    Object.assign(run, { decisions: [], candidates: [], ranked_candidate_ids: [], status: "unavailable", next_best_action: "supply sanitized candidates" });
  }, { performance: null });
  const tree = render(readyModel(payload));
  assert.ok(getByRole(tree, "heading", { level: 2, name: "No opportunities yet" }));
  assert.match(textContent(tree), /never invents a category, market, or product/);
  assert.match(textContent(tree), /Provider next step: supply sanitized candidates/);
  assert.equal(queryByRole(tree, "button"), null, "no fake save or add action");
  assert.match(textContent(getByRole(tree, "region", { name: "Performance" })), /Not available/);
});

test("notices: stale data is a status, and provider integrity problems are an alert", () => {
  const stale = render(readyModel({ ...demoPayload, asOf: "2026-09-27T12:00:00Z" }));
  assert.match(textContent(getByRole(stale, "status", { name: /^Data may be stale\./ })), /older than 24 hours/);

  const tampered = render(readyModel(withRun((run) => {
    run.safety.launch_authorized = true;
  })));
  const alert = getByRole(tampered, "alert", { name: /Provider response deviates from the read-only contract/ });
  assert.match(textContent(alert), /launch_authorized/);
  assert.match(textContent(alert), /cannot authorize launches or actions/);
  assert.deepEqual(definitionOf(tampered, "Launch authorization"), ["Not authorized", "this page cannot grant it"]);

  const partial = render(readyModel(withRun((run) => {
    run.decisions.push(null);
  })));
  assert.match(textContent(getByRole(partial, "status", { name: /^Some provider records were skipped\./ })), /incomplete/);
});

// ---------------------------------------------------------------- performance

test("performance: demo fixture values are labelled, gaps are shown as gaps, and no zero is invented", () => {
  const tree = render(readyModel());
  const panel = getByRole(tree, "region", { name: "Performance" });
  const provenance = getByRole(panel, "status", { name: /Demo fixture data/ });
  assert.equal(provenance.attrs["data-performance-provenance"], "fixture");
  assert.match(textContent(provenance), /invented to show the layout\. They are not observed performance/);
  const table = getByRole(panel, "table", { name: /Orders per week \(demo\): value for each period/ });
  const rows = Object.fromEntries(rowsOf(table).map((row) => cellsOf(row)));
  assert.deepEqual(rows, { "Wk 1": "12", "Wk 2": "15", "Wk 3": "14", "Wk 4": "Not available", "Wk 5": "19", "Wk 6": "22", "Wk 7": "Not available", "Wk 8": "27" });
  assert.match(textContent(panel), /2 periods have no data and are shown as gaps, not as zero\./);
  assert.equal(queryByRole(panel, "img"), null);
});

test("performance: with no observed records the panel says not available and offers no chart", () => {
  const tree = render(readyModel({ ...demoPayload, performance: null }));
  const panel = getByRole(tree, "region", { name: "Performance" });
  assert.match(textContent(panel), /Not available\. No observed performance records are connected to this dashboard\./);
  assert.match(textContent(panel), /never estimated or filled in with zeros/);
  assert.equal(queryByRole(panel, "table"), null);
  assert.equal(hasText(panel, "Demo fixture data"), false);
});

test("performance: observed series are called observed, without the demo label", () => {
  const observed = [{ id: "orders", label: "Orders per week", unit: "count", provenance: "observed", points: [{ periodLabel: "Wk 1", value: 0 }, { periodLabel: "Wk 2", value: 4 }] }];
  const panel = getByRole(render(readyModel({ ...demoPayload, performance: observed })), "region", { name: "Performance" });
  assert.match(textContent(panel), /Observed records/);
  assert.equal(hasText(panel, "Demo fixture data"), false);
  const rows = Object.fromEntries(rowsOf(getByRole(panel, "table")).map((row) => cellsOf(row)));
  assert.deepEqual(rows, { "Wk 1": "0", "Wk 2": "4" }, "a real zero is shown as zero");
});

// ---------------------------------------------------------------- wiring

const renderWithClient = (client, element) =>
  parseHtml(renderToStaticMarkup(createElement(QueryClientProvider, { client }, element)));

test("page: the route component renders the loading state first and needs no backend", () => {
  const client = new QueryClient();
  const tree = renderWithClient(client, createElement(OwnerDashboardPage));
  assert.ok(getByRole(tree, "status", { name: /Loading owner dashboard…/ }));
  assert.ok(getByRole(tree, "status", { name: /^Demo data\./ }));
  client.clear();
});

test("hook: loaded source data flows through to the ready dashboard", async () => {
  const client = new QueryClient();
  await client.prefetchQuery({ queryKey: ["owner-dashboard", fixtureSource.id], queryFn: () => fixtureSource.load() });
  const Harness = () => {
    const { viewModel } = useOwnerDashboard(fixtureSource);
    return createElement(OwnerDashboardView, { viewModel, selectedId: null, onSelect() {}, onRetry() {} });
  };
  const tree = renderWithClient(client, createElement(Harness));
  assert.ok(getByRole(tree, "heading", { level: 2, name: "Adjustable desk lamp (demo)" }));
  assert.equal(queryByRole(tree, "alert"), null);
  client.clear();
});

test("hook: a failing source never leaks its internal error text into the page", async () => {
  const failing = { id: "down", dataMode: "fixture_demo", load: async () => { throw new Error("secret-internal-detail: connection refused at 10.0.0.7"); } };
  const client = new QueryClient();
  await client.prefetchQuery({ queryKey: ["owner-dashboard", failing.id], queryFn: () => failing.load(), retry: false });
  const Harness = () => {
    const { viewModel } = useOwnerDashboard(failing);
    return createElement(OwnerDashboardView, { viewModel, selectedId: null, onSelect() {}, onRetry() {} });
  };
  const tree = renderWithClient(client, createElement(Harness));
  assert.equal(queryByRole(tree, "table"), null);
  assert.equal(hasText(tree, "secret-internal-detail"), false);
  assert.equal(hasText(tree, "10.0.0.7"), false);
  client.clear();
});
