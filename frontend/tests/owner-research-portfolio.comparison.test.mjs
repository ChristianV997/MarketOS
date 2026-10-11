/**
 * Owner Research Portfolio comparison: real component rendering tests.
 *
 * Test-only canonical packets exercise the existing synthesis projection; these
 * values are not fixtures shipped to the live UI.
 */
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { test } from "node:test";

import { importSrc } from "./helpers/load-ts.mjs";
import { CTX, FEATURE, NOW, packetWith, portfolioPayload, rankedRow } from "./helpers/owner-research-builders.mjs";

const { OwnerResearchWorkspace } = await importSrc(`${FEATURE}/components/OwnerResearchWorkspace`);
const { adaptRankingPacket } = await importSrc(`${FEATURE}/lib/adaptRankingReadModel`);
const { adaptPortfolioPayload } = await importSrc(`${FEATURE}/lib/adaptPortfolioReadModel`);

function readyModels() {
  const packet = packetWith(
    [
      rankedRow("cand-a", { rankIndex: 0, title: "Alpha lamp" }),
      rankedRow("cand-b", { rankIndex: 1, title: "Beta bottle" }),
      rankedRow("cand-c", { rankIndex: 2, title: "Gamma cable" }),
      rankedRow("cand-d", { rankIndex: 3, title: "Delta kettle" }),
    ],
    { fingerprint: { evidenceMode: "manual" } },
  );
  return {
    ranking: adaptRankingPacket({ packet, loading: false, loadError: null, nowMs: NOW }),
    portfolio: adaptPortfolioPayload(portfolioPayload(), CTX),
  };
}

function findElements(node, predicate, out = []) {
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) {
    for (const child of node) findElements(child, predicate, out);
    return out;
  }
  if (predicate(node)) out.push(node);
  if (node.props) findElements(node.props.children, predicate, out);
  return out;
}

test("comparison workspace exposes an empty selection state and a labelled current-candidate toggle", () => {
  const html = renderToStaticMarkup(createElement(OwnerResearchWorkspace, readyModels()));

  assert.match(html, /Compare opportunities/);
  assert.match(html, /data-comparison-count="0"/);
  assert.match(html, /No candidates selected for comparison/);
  assert.match(html, /data-comparison-toggle/);
  assert.match(html, /aria-pressed="false"/);
  assert.match(html, />Add to comparison</);
  assert.match(html, /does not calculate a winner or a new score/i);
  assert.match(html, /Public-market and consumer-attention signals are context, not supplier proof/i);
});

test("comparison selection toggles candidate IDs and never exceeds three", async () => {
  const { MAX_COMPARISON_CANDIDATES, toggleComparisonCandidate } = await importSrc(`${FEATURE}/lib/comparisonSelection`);

  assert.equal(MAX_COMPARISON_CANDIDATES, 3);
  assert.deepEqual(toggleComparisonCandidate([], "cand-a"), ["cand-a"]);
  assert.deepEqual(toggleComparisonCandidate(["cand-a", "cand-b"], "cand-c"), ["cand-a", "cand-b", "cand-c"]);
  assert.deepEqual(toggleComparisonCandidate(["cand-a", "cand-b", "cand-c"], "cand-d"), ["cand-a", "cand-b", "cand-c"]);
  assert.deepEqual(toggleComparisonCandidate(["cand-a", "cand-b", "cand-c"], "cand-b"), ["cand-a", "cand-c"]);
});

test("comparison table preserves canonical evidence classes and the supplied backend order", async () => {
  const { OpportunityComparison } = await importSrc(`${FEATURE}/components/OpportunityComparison`);
  const alphaPillars = [
    { pillarId: "market_evidence", label: "Market evidence", status: "available", score: 0.58, detail: "Public snapshot", evidenceClass: "public_observed" },
    { pillarId: "supplier_feasibility", label: "Supplier feasibility", status: "partial", score: null, detail: "Claim only", evidenceClass: "supplier_claimed" },
    { pillarId: "consumer_attention", label: "Consumer attention", status: "unavailable", score: null, detail: null, evidenceClass: "not_run" },
  ];
  const betaPillars = [
    { pillarId: "market_evidence", label: "Market evidence", status: "partial", score: null, detail: null, evidenceClass: "public_observed" },
    { pillarId: "supplier_feasibility", label: "Supplier feasibility", status: "available", score: 0.72, detail: "Documents received", evidenceClass: "supplier_documented" },
    { pillarId: "consumer_attention", label: "Consumer attention", status: "available", score: 0.31, detail: "Manual review", evidenceClass: "fixture" },
  ];
  const packet = packetWith(
    [
      rankedRow("cand-alpha", {
        rankIndex: 1,
        title: "Alpha lamp",
        evidenceMode: "manual",
        evidenceClass: "public_observed",
        supplierEvidenceClass: "supplier_claimed",
        consumerEvidenceClass: "not_run",
        sourceFamily: "manual_import",
        nextBestAction: "collect_supplier_documentation",
        assumptions: ["planning_margin_assumption"],
        missingEvidence: ["supplier_documentation"],
        pillarCells: alphaPillars,
      }),
      rankedRow("cand-beta", {
        rankIndex: 0,
        title: "Beta bottle",
        evidenceMode: "fixture_only",
        evidenceClass: "fixture",
        supplierEvidenceClass: "supplier_documented",
        consumerEvidenceClass: "fixture",
        sourceFamily: "public_market_snapshot",
        nextBestAction: "review_consumer_signal",
        assumptions: [],
        pillarCells: betaPillars,
      }),
    ],
    { fingerprint: { evidenceMode: "manual" } },
  );
  const rows = adaptRankingPacket({ packet, loading: false, loadError: null, nowMs: NOW }).rows;
  const html = renderToStaticMarkup(createElement(OpportunityComparison, { rows, onRemove() {} }));
  const text = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").toLowerCase();

  assert.match(html, /data-comparison-table/);
  assert.match(html, /<caption[^>]*>[^<]*opportunit/i);
  assert.match(html, /role="region"[^>]*tabindex="0"/);
  assert.match(html, /<th scope="col"/);
  assert.match(html, /<th scope="row"/);
  assert.ok(html.indexOf("Alpha lamp") < html.indexOf("Beta bottle"), "candidate order follows the supplied backend order, not rankIndex re-sorting");
  for (const expected of [
    "Supplier evidence class",
    "Public-market context",
    "Consumer-attention evidence",
    "Evidence mode",
    "Next action from synthesis",
    "Planning assumptions",
    "supplier_documentation",
    "planning_margin_assumption",
    "Manual import",
    "Fixture only",
    "Supplier claimed",
    "Supplier documented",
    "Not reported",
  ]) {
    assert.ok(text.includes(expected.toLowerCase()), `${expected} remains visible in the comparison`);
  }
  assert.match(text, /reported pillar scores are not combined into another score/i);
  assert.doesNotMatch(text, /comparison score|overall opportunity score/i);

  const removedIds = [];
  const tree = OpportunityComparison({ rows, onRemove: (candidateId) => removedIds.push(candidateId) });
  const removeButtons = findElements(tree, (node) => node.type === "button");
  assert.equal(removeButtons.length, 2);
  for (const button of removeButtons) button.props.onClick();
  assert.deepEqual(removedIds, rows.map((row) => row.candidateId));
  assert.ok(removeButtons.every((button, index) => button.props["aria-label"].includes(rows[index].candidateId)));
});
