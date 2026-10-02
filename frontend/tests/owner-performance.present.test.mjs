import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { DEMO_OBSERVED_REPORT, DEMO_PARTIAL_REPORT } from "../src/features/owner-performance/fixtures/demoReport.ts";
import { presentCampaigns, presentMeasures, textSummary } from "../src/features/owner-performance/lib/presentReport.ts";

test("observed demo displays contract amounts and does not claim lift", () => {
  const measures = presentMeasures(DEMO_OBSERVED_REPORT);
  const byKey = Object.fromEntries(measures.map((item) => [item.key, item]));
  assert.equal(byKey.revenue.amountText, "100.00");
  assert.equal(byKey.contribution.amountText, "42.00");
  assert.equal(byKey.realized_profit.availability, "available");
  const campaigns = presentCampaigns(DEMO_OBSERVED_REPORT);
  assert.equal(campaigns[0].lift, "Not claimed. Causal lift is unsupported.");
  assert.equal(campaigns[0].causalAttribution, "not claimed");
  assert.match(textSummary(DEMO_OBSERVED_REPORT), /Campaign lift is not claimed/);
});

test("missing refunds stay unavailable and are not rendered as zero", () => {
  const refunds = presentMeasures(DEMO_PARTIAL_REPORT).find((item) => item.key === "refunds");
  assert.equal(refunds?.availability, "unavailable");
  assert.equal(refunds?.amountText, "Unavailable");
  assert.match(refunds?.summary ?? "", /Not zero/);
  const contribution = presentMeasures(DEMO_PARTIAL_REPORT).find((item) => item.key === "contribution");
  assert.equal(contribution?.availability, "unavailable");
});

test("explicit zero is distinct from unavailable", () => {
  const report = {
    ...DEMO_OBSERVED_REPORT,
    refunds: { ...DEMO_OBSERVED_REPORT.refunds, amount: "0", status: "observed" },
    explicit_zeros: ["refunds"],
  };
  const refunds = presentMeasures(report).find((item) => item.key === "refunds");
  assert.equal(refunds?.availability, "explicit_zero");
  assert.match(refunds?.summary ?? "", /explicit zero/);
});

test("dashboard source does not invent a route or recompute profit", async () => {
  const source = await readFile(new URL("../src/features/owner-performance/components/OwnerPerformanceDashboard.tsx", import.meta.url), "utf8");
  assert.match(source, /Time series: not in owner-performance-report-v1/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /<table/);
  assert.match(source, /ArrowDown/);
  assert.doesNotMatch(source, /fetch\(/);
  assert.doesNotMatch(source, /react-router/);
  assert.doesNotMatch(source, /contribution\.amount\s*-/);
});

test("unmounted backend route is not probed by the default dashboard path", async () => {
  const [componentSource, hookSource] = await Promise.all([
    readFile(new URL("../src/features/owner-performance/components/OwnerPerformanceDashboard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/features/owner-performance/hooks/useOwnerPerformance.ts", import.meta.url), "utf8"),
  ]);

  assert.match(componentSource, /useOwnerPerformance\(\)/);
  assert.doesNotMatch(componentSource, /useOwnerPerformance\(\{\s*enabled:\s*true/);
  assert.match(hookSource, /enabled: options\.enabled \?\? false/);
});
