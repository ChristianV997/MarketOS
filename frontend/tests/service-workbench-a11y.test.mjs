import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const tableUrl = new URL("../src/features/service-delivery-workbench/components/PipelineTable.tsx", import.meta.url);
const workflowUrl = new URL("../src/features/service-delivery-workbench/components/EngagementWorkflow.tsx", import.meta.url);
const chromeUrl = new URL("../src/features/service-delivery-workbench/components/WorkbenchChrome.tsx", import.meta.url);
const pageUrl = new URL("../src/pages/ServiceDeliveryWorkbench.tsx", import.meta.url);

function srgbChannel(value) {
  const channel = value / 255;
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex) {
  const raw = hex.replace("#", "");
  const r = srgbChannel(parseInt(raw.slice(0, 2), 16));
  const g = srgbChannel(parseInt(raw.slice(2, 4), 16));
  const b = srgbChannel(parseInt(raw.slice(4, 6), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(foreground, background) {
  const first = relativeLuminance(foreground);
  const second = relativeLuminance(background);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

test("workbench secondary text uses zinc-400, not zinc-500, against the dark panel", async () => {
  const workbenchBg = "#111113";
  assert.ok(contrastRatio("#a1a1aa", workbenchBg) >= 4.5, "Tailwind zinc-400 must meet WCAG AA on #111113");
  assert.ok(contrastRatio("#71717a", workbenchBg) < 4.5, "Tailwind zinc-500 fails WCAG AA on #111113");

  const table = await readFile(tableUrl, "utf8");
  const workflow = await readFile(workflowUrl, "utf8");
  const chrome = await readFile(chromeUrl, "utf8");
  const page = await readFile(pageUrl, "utf8");
  assert.doesNotMatch(table, /text-zinc-500/);
  assert.doesNotMatch(workflow, /text-zinc-500/);
  assert.doesNotMatch(chrome, /text-zinc-500/);
  assert.match(table, /text-zinc-400/);
  assert.match(chrome, /placeholder:text-zinc-400/);
  assert.doesNotMatch(chrome, /opacity-80/);
  assert.match(page, /focus:text-zinc-50/);
  assert.match(page, /href="#pipeline-heading"/);
});

test("skip link targets a focusable pipeline heading and the table overflow is keyboard reachable", async () => {
  const table = await readFile(tableUrl, "utf8");
  const page = await readFile(pageUrl, "utf8");
  const shell = await readFile(new URL("../src/components/layout/Shell.tsx", import.meta.url), "utf8");
  assert.match(table, /id="pipeline-heading" tabIndex=\{-1\}/);
  assert.match(table, /aria-label="Scrollable service pipeline table"/);
  assert.match(shell, /href="#operator-main"/);
  assert.match(shell, /id="operator-main"/);
  assert.match(shell, /tabIndex=\{-1\}/);
  assert.match(page, /overflow-x-auto/);
  assert.doesNotMatch(page, /overflow-x-hidden/);
});

test("pipeline rows are native table rows with a named button, not row widgets", async () => {
  const table = await readFile(tableUrl, "utf8");
  const page = await readFile(pageUrl, "utf8");
  assert.match(table, /<table className="min-w-full text-left text-sm">/);
  assert.doesNotMatch(table, /<tr[^>]*tabIndex=/);
  assert.doesNotMatch(table, /<tr\s+tabIndex=/);
  assert.doesNotMatch(table, /aria-selected/);
  assert.doesNotMatch(table, /role="row"/);
  assert.match(table, /type="button"/);
  assert.match(table, /aria-pressed=\{selected\}/);
  assert.match(table, /emptyCopy/);
  assert.doesNotMatch(table, /No engagements match\. Clear filters to recover the source list\./);
  assert.match(table, /aria-current=\{selected \? "true" : undefined\}/);
  assert.match(table, /ArrowDown/);
  assert.match(table, /Home/);
  assert.match(table, /End/);
  assert.match(page, /button\[aria-pressed='true'\]/);
  assert.match(page, /movePipelineFocus/);
  assert.match(page, /Filter\/auto-select must not steal focus from the search field/);
});

test("unserved GET JSON including HTTP error bodies is adapted, never demo-substituted", async () => {
  const hook = await readFile(new URL("../src/features/service-delivery-workbench/hooks/useServiceDeliveryWorkbench.ts", import.meta.url), "utf8");
  assert.doesNotMatch(hook, /buildDemoProjection/);
  assert.match(hook, /response.json\(\)\.catch/);
  assert.match(hook, /method: "GET"/);
  assert.match(hook, /useMemo/);
});

test("compose filter stops after the display window plus one bounded marker", async () => {
  const compose = await readFile(new URL("../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts", import.meta.url), "utf8");
  const filter = await readFile(new URL("../src/features/service-delivery-workbench/lib/filterEngagements.ts", import.meta.url), "utf8");
  assert.match(compose, /maxResults: WORKBENCH_FILTER_WINDOW \+ 1/);
  assert.match(filter, /maxResults/);
});

test("JSON previews are bounded, wrapping, and keyboard-focusable regions", async () => {
  const workflow = await readFile(workflowUrl, "utf8");
  assert.match(workflow, /function JsonPreview/);
  assert.match(workflow, /role="region"/);
  assert.match(workflow, /tabIndex=\{0\}/);
  assert.match(workflow, /aria-label=\{label\}/);
  assert.match(workflow, /overflow-auto/);
  assert.match(workflow, /whitespace-pre-wrap/);
  assert.match(workflow, /break-all/);
  assert.match(workflow, /max-h-40/);
  assert.match(workflow, /max-h-64/);
  assert.match(workflow, /focus-visible:outline/);
  assert.match(workflow, /label="Draft report JSON preview"/);
  assert.match(workflow, /label="Client-safe export JSON preview"/);
  assert.match(workflow, /label="Rejected export JSON preview"/);
});
