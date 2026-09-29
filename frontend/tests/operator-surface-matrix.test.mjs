import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const cockpitRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);
const workbenchRoot = new URL("../src/features/service-delivery-workbench/", import.meta.url);

test("operator surfaces cover truthful states without inventing available_read_only", async () => {
  const composeCockpit = await readFile(new URL("lib/composeCockpitViewModel.ts", cockpitRoot), "utf8");
  const composeWorkbench = await readFile(new URL("lib/composeWorkbenchViewModel.ts", workbenchRoot), "utf8");
  const contracts = await readFile(new URL("contracts/serviceEngagementProjection.ts", workbenchRoot), "utf8");
  for (const token of ["unavailable", "fixture", "manual_import", "partial", "stale", "blocked"]) {
    assert.match(composeWorkbench + contracts + composeCockpit, new RegExp(token));
  }
  assert.match(composeCockpit, /blocked/);
  assert.doesNotMatch(composeWorkbench, /available_read_only/);
  assert.match(composeWorkbench, /liveEndpointUnavailable: true/);
  assert.match(composeWorkbench, /never emit success/);
});

test("filters preserve server order and never re-rank", async () => {
  const cockpitFilter = await readFile(new URL("lib/filterCandidates.ts", cockpitRoot), "utf8");
  const workbenchFilter = await readFile(new URL("lib/filterEngagements.ts", workbenchRoot), "utf8");
  assert.doesNotMatch(cockpitFilter, /\.sort\(/);
  assert.doesNotMatch(workbenchFilter, /\.sort\(/);
  assert.match(cockpitFilter, /Never sorts/);
  assert.match(workbenchFilter, /reordering/);
});

test("exports remain client-safe and mutation-free", async () => {
  const cockpitExport = await readFile(new URL("lib/exportClientSafeReport.ts", cockpitRoot), "utf8");
  const workbenchExport = await readFile(new URL("lib/exportClientSafeEngagement.ts", workbenchRoot), "utf8");
  assert.match(cockpitExport, /mutated: false/);
  assert.match(workbenchExport, /mutated: false/);
  assert.match(cockpitExport, /containsSecretShapedValue/);
  assert.match(workbenchExport, /containsSecretShapedValue/);
  assert.match(workbenchExport, /data_inadequate/);
});

test("accessibility contracts remain keyboard, live-region, table, and reduced-motion", async () => {
  const cockpitPage = await readFile(new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url), "utf8");
  const workbenchPage = await readFile(new URL("../src/pages/ServiceDeliveryWorkbench.tsx", import.meta.url), "utf8");
  const cockpitTable = await readFile(new URL("components/RankedCandidatesPanel.tsx", cockpitRoot), "utf8");
  const workbenchTable = await readFile(new URL("components/PipelineTable.tsx", workbenchRoot), "utf8");
  const css = await readFile(new URL("../src/index.css", import.meta.url), "utf8");
  const banner = await readFile(new URL("components/CockpitStatusBanner.tsx", cockpitRoot), "utf8");
  const chrome = await readFile(new URL("components/WorkbenchChrome.tsx", workbenchRoot), "utf8");
  assert.match(cockpitPage, /Skip to ranked candidates/);
  assert.match(workbenchPage, /Skip to service pipeline/);
  assert.match(cockpitTable, /ArrowDown|adjacentCandidateIndex/);
  assert.match(workbenchTable, /ArrowDown/);
  assert.match(workbenchTable, /scope="col"/);
  assert.match(cockpitTable, /scope="col"/);
  assert.match(banner, /aria-live="polite"/);
  assert.match(chrome, /aria-live="polite"/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /:focus-visible/);
});

test("Higgsfield remains unavailable draft metadata", async () => {
  const creative = await readFile(new URL("lib/creativeAssetContract.ts", workbenchRoot), "utf8");
  assert.match(creative, /generation_enabled: false/);
  assert.match(creative, /publication_enabled: false/);
  assert.doesNotMatch(creative, /apify/i);
});
