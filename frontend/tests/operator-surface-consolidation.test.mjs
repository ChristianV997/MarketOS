import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const root = new URL("../src/", import.meta.url);

test("shell is the only skip-to-main; pages keep in-page skips", async () => {
  const shell = await readFile(new URL("components/layout/Shell.tsx", root), "utf8");
  const sidebar = await readFile(new URL("components/layout/Sidebar.tsx", root), "utf8");
  const workbench = await readFile(new URL("pages/ServiceDeliveryWorkbench.tsx", root), "utf8");
  const cockpit = await readFile(new URL("pages/FirstPhaseEvidenceCockpit.tsx", root), "utf8");
  const skipCount = shell.split("Skip to main content").length - 1;
  assert.equal(skipCount, 1);
  assert.match(shell, /SKIP_TO_MAIN_ID/);
  assert.match(shell, /OPERATOR_MAIN_ID/);
  assert.doesNotMatch(shell, /sr-only focus:not-sr-only/);
  assert.doesNotMatch(workbench, /Skip to main content/);
  assert.doesNotMatch(cockpit, /Skip to main content/);
  assert.match(workbench, /Skip to service pipeline/);
  assert.match(cockpit, /Skip to ranked candidates/);
  assert.match(sidebar, /max-md:-translate-x-full/);
  assert.match(shell, /shouldCloseDrawerOnKey/);
  assert.match(shell, /prefers-reduced-motion|animate-pulse-slow/);
});

test("consolidated operator surfaces stay GET-only and do not add a second client", async () => {
  const workbenchHook = await readFile(
    new URL("features/service-delivery-workbench/hooks/useServiceDeliveryWorkbench.ts", root),
    "utf8",
  );
  const cockpitHook = await readFile(
    new URL("features/first-phase-cockpit/hooks/useFirstPhaseEvidenceCockpit.ts", root),
    "utf8",
  );
  const events = await readFile(new URL("lib/canonicalEventsApi.ts", root), "utf8");
  assert.match(workbenchHook, /method: "GET"/);
  assert.doesNotMatch(workbenchHook, /method:\s*["']POST["']/);
  assert.match(cockpitHook, /usePhase1Readiness/);
  assert.match(cockpitHook, /useBenchmarkMatrix/);
  assert.doesNotMatch(cockpitHook, /fetch\(/);
  assert.doesNotMatch(events, /\/api\/phase1\/evidence-cockpit/);
  assert.match(events, /\/api\/phase1\/readiness/);
  assert.match(events, /\/api\/phase1\/benchmark-matrix/);
});
