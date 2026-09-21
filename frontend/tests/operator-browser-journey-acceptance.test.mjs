/**
 * Operator-journey browser acceptance contracts.
 *
 * Durable path: scripts/ai/run_operator_browser_acceptance.py
 * (Orca embedded browser or installed Chrome; fixture harness by default).
 *
 * These Node tests prove the fixture harness + runner stay GET-only and never
 * treat unavailable API modes as demo-success. They do not duplicate #277
 * source-contract matrix tests or #281/#290 runners.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const harnessUrl = new URL("./fixtures/operator-journey/harness.html", import.meta.url);
const runnerPath = path.join(repoRoot, "scripts", "ai", "run_operator_browser_acceptance.py");

test("operator journey harness encodes skip links, live region, evidence classes, and no mutation controls", async () => {
  const html = await readFile(harnessUrl, "utf8");
  assert.match(html, /Skip to service pipeline/);
  assert.match(html, /Skip to ranked candidates/);
  assert.match(html, /Skip to events table/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /role="grid"/);
  assert.match(html, /data_inadequate/);
  assert.match(html, /fixture/);
  assert.match(html, /manual/);
  assert.match(html, /simulated/);
  assert.match(html, /unknown/);
  assert.match(html, /Safe export preview/);
  assert.match(html, /Not live validated|not live proof|not live validated/i);
  assert.match(html, /POST control is intentionally omitted/);
  assert.doesNotMatch(html, /method:\s*["']POST["']/);
  assert.doesNotMatch(html, /<form/i);
  assert.doesNotMatch(html, /evidence class:\s*live_validated/i);
  assert.match(html, /prefers-reduced-motion/);
  assert.match(html, /mobile-only/);
  assert.match(html, /desktop-only/);
});

test("operator journey harness instruments fetch methods into window.__mosRequests", async () => {
  const html = await readFile(harnessUrl, "utf8");
  assert.match(html, /window\.__mosRequests/);
  assert.match(html, /init\.method/);
  assert.match(html, /"GET"\)\.toUpperCase\(\)/);
  assert.match(html, /Network method log/);
});

test("acceptance runner source stays loopback-only and fail-closed on mutations", async () => {
  const source = await readFile(runnerPath, "utf8");
  assert.match(source, /MUTATING_METHODS/);
  assert.match(source, /POST.*PUT.*PATCH.*DELETE|frozenset\(\{"POST"/);
  assert.match(source, /127\.0\.0\.1/);
  assert.match(source, /not demo-success/);
  assert.match(source, /browser_proof/);
  assert.match(source, /orca/);
  assert.match(source, /dump-dom|--dump-dom/);
  assert.doesNotMatch(source, /pip install|npm install|npx playwright install/i);
});

test("python fixture acceptance path runs without claiming browser proof when --browser none", () => {
  const completed = spawnSync(
    process.env.PYTHON || "python",
    [runnerPath, "--browser", "none", "--skip-viewports", "--json"],
    {
      cwd: repoRoot,
      encoding: "utf8",
      timeout: 60_000,
      env: { ...process.env },
    },
  );
  assert.equal(completed.status, 0, completed.stderr || completed.stdout);
  const start = (completed.stdout || "").indexOf("{");
  assert.ok(start >= 0, "expected JSON report");
  const report = JSON.parse(completed.stdout.slice(start));
  assert.equal(report.schema, "MarketOS.OperatorBrowserAcceptance.v1");
  assert.equal(report.browser_method, "none");
  assert.equal(report.browser_proof, false);
  assert.match(String(report.status), /^passed/);
  assert.deepEqual(report.routes, ["/operator/services", "/operator/first-phase", "/operator/events"]);
  const spa404 = report.cases.filter((item) => String(item.id).startsWith("fixture-server-spa-"));
  assert.equal(spa404.length, 3);
  assert.ok(spa404.every((item) => item.passed && item.http_status === 404));
  const unavailable = report.cases.filter((item) => ["down", "429", "500", "malformed"].includes(item.api_mode));
  assert.ok(unavailable.length >= 3);
});
