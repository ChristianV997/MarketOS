import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  isDrawerMode,
  shouldCloseDrawerOnKey,
  shouldCloseDrawerOnSkip,
} from "../src/components/layout/sidebarDrawer.ts";
import { adaptServiceProjection } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { composeWorkbenchViewModel } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { buildClientSafeServiceExport } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";
import { EMPTY_FILTERS } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { buildProducerPlaneEnvelope } from "../src/features/service-delivery-workbench/fixtures/producerPlaneEnvelope.ts";
import {
  composeCockpitViewModel,
  normalizeEvidenceMode,
} from "../src/features/first-phase-cockpit/lib/composeCockpitViewModel.ts";
import { buildClientSafeExport } from "../src/features/first-phase-cockpit/lib/exportClientSafeReport.ts";

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

test("drawer widths and escape close stay on the shell helper", () => {
  for (const width of [320, 390, 420, 767]) assert.equal(isDrawerMode(width), true);
  for (const width of [768, 1280]) assert.equal(isDrawerMode(width), false);
  assert.equal(shouldCloseDrawerOnKey("Escape", { open: true, drawerMode: true }), true);
  assert.equal(shouldCloseDrawerOnKey("Escape", { open: true, drawerMode: false }), false);
  assert.equal(shouldCloseDrawerOnSkip(true, true), true);
});

test("integrated workbench and cockpit compose stay fixture-honest and ordered", () => {
  const plane = buildProducerPlaneEnvelope();
  const poisoned = {
    ...plane,
    availability: "manual_import",
    live_endpoint_status: "available_read_only",
    engagements: plane.engagements.map((row, index) => index === 4
      ? {
        ...row,
        economics: {
          ...row.economics,
          fee: { ...row.economics.fee, evidence_class: "live_validated" },
        },
      }
      : row),
  };
  const adapted = adaptServiceProjection(poisoned, "live-get");
  assert.equal(adapted.rejected, false);
  const ids = adapted.projection.engagements.map((row) => row.engagement_id);
  assert.deepEqual(ids, plane.engagements.map((row) => row.engagement_id));
  const approved = adapted.projection.engagements[4];
  assert.notEqual(approved.economics.fee?.evidence_class, "live_validated");
  const view = composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection: adapted.projection,
    filters: EMPTY_FILTERS,
    selectedId: ids[0],
  });
  assert.notEqual(view.surface, "success");
  const exported = buildClientSafeServiceExport(approved);
  assert.equal(/"live_validated"/.test(JSON.stringify(exported.payload ?? {})), false);

  assert.equal(normalizeEvidenceMode("fixture_demo"), "fixture_only");
  assert.equal(normalizeEvidenceMode("unknown"), "unknown");
  assert.equal(normalizeEvidenceMode("live_readonly"), "live_readonly");
  assert.equal(normalizeEvidenceMode("live_validated"), "unknown");
  const cockpit = composeCockpitViewModel({
    phase1Readiness: null,
    benchmark: null,
    publicMarket: null,
    researchPortfolio: null,
    readinessError: true,
    benchmarkError: true,
    publicMarketError: true,
    researchError: true,
    isLoading: false,
  });
  assert.notEqual(cockpit.state, "success");
  assert.equal(cockpit.fingerprint.evidenceMode, "unknown");
  assert.throws(
    () => buildClientSafeExport(cockpit, "offline-acceptance"),
    /client_safe_export_rejected_unknown_evidence/,
  );
});
