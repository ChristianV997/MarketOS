import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { buildOneClientProjection } from "../src/features/service-delivery-workbench/fixtures/buildFixtures.ts";
import { buildClientSafeServiceExport } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";

function renderStatusBanner(surface, message) {
  return `<div role="status" aria-live="polite" aria-atomic="true" data-surface="${surface}"><p>${message}</p></div>`;
}

function renderPipeline(rows, selectedId) {
  const body = rows.map((row) => (
    `<tr aria-selected="${row.engagement_id === selectedId}" tabindex="${row.engagement_id === selectedId ? 0 : -1}"><th scope="row">${row.intake.display_name}</th></tr>`
  )).join("");
  return `<table><thead><tr><th scope="col">Client</th></tr></thead><tbody>${body}</tbody></table>`;
}

test("react component contracts: live region, table semantics, data_inadequate copy", async () => {
  const workflow = await readFile(new URL("../src/features/service-delivery-workbench/components/EngagementWorkflow.tsx", import.meta.url), "utf8");
  const chrome = await readFile(new URL("../src/features/service-delivery-workbench/components/WorkbenchChrome.tsx", import.meta.url), "utf8");
  const table = await readFile(new URL("../src/features/service-delivery-workbench/components/PipelineTable.tsx", import.meta.url), "utf8");
  assert.match(chrome, /export function WorkbenchStatusBanner/);
  assert.match(chrome, /aria-live="polite"/);
  assert.match(table, /export function PipelineTable/);
  assert.match(workflow, /export function EngagementWorkflow/);

  const engagement = buildOneClientProjection().engagements[0];
  const banner = renderStatusBanner("blocked", "Selected engagement is data_inadequate.");
  const pipeline = renderPipeline([engagement], engagement.engagement_id);
  const exported = buildClientSafeServiceExport(engagement);
  assert.match(banner, /aria-live="polite"/);
  assert.match(pipeline, /<table/);
  assert.match(pipeline, /aria-selected="true"/);
  assert.equal(exported.accepted, false);
  assert.match(workflow, /how_to_provide/);
});
