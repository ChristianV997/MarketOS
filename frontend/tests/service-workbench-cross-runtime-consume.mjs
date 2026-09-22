import { readFile } from "node:fs/promises";
import { UNSERVED_GET_ENVELOPE } from "../src/features/service-delivery-workbench/lib/unservedGetEnvelope.ts";
import { adaptServiceProjection } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { composeWorkbenchViewModel } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { EMPTY_FILTERS } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";

const path = process.argv[2];
const mode = process.argv[3] || "live-get";
if (!path && mode === "live-get") {
  process.stderr.write("usage: service-workbench-cross-runtime-consume.mjs <route-json> [live-get|unserved|http-error]\n");
  process.exit(2);
}

let adapted;
let errorMessage = null;
if (mode === "unserved") {
  adapted = adaptServiceProjection(UNSERVED_GET_ENVELOPE, "unavailable");
} else if (mode === "http-error") {
  adapted = adaptServiceProjection(UNSERVED_GET_ENVELOPE, "unavailable");
  errorMessage = "Canonical /api/service-delivery/workbench unavailable (error). This is not a fixture success state.";
} else {
  const raw = JSON.parse(await readFile(path, "utf8"));
  adapted = adaptServiceProjection(raw, "live-get");
  if (adapted.rejected) errorMessage = adapted.rejection_reason;
}

const view = composeWorkbenchViewModel({
  isLoading: false,
  errorMessage,
  projection: adapted.projection,
  filters: EMPTY_FILTERS,
  selectedId: null,
});

const evidenceClasses = adapted.projection.engagements.flatMap((row) =>
  row.evidence.map((item) => item.evidence_class),
);

process.stdout.write(`${JSON.stringify({
  rejected: adapted.rejected,
  rejection_reason: adapted.rejection_reason,
  availability: adapted.projection.availability,
  live_endpoint_status: adapted.projection.live_endpoint_status,
  input_contract: adapted.projection.input_contract,
  surface: view.surface,
  liveEndpointUnavailable: view.liveEndpointUnavailable,
  ids: adapted.projection.engagements.map((row) => row.engagement_id),
  services: adapted.projection.engagements.map((row) => row.service_id),
  lifecycles: adapted.projection.engagements.map((row) => row.lifecycle_state),
  data_inadequate: adapted.projection.engagements.map((row) => row.eligibility.data_inadequate),
  missing_data: adapted.projection.engagements.map((row) => row.missing_data),
  fees: adapted.projection.engagements.map((row) => row.economics.fee.amount_label),
  currencies: adapted.projection.engagements.map((row) => row.economics.fee.currency),
  frontend_calculates: adapted.projection.engagements.map((row) => row.economics.frontend_calculates),
  economics_authority: adapted.projection.engagements.map((row) => row.economics.authority),
  evidence_classes: evidenceClasses,
  any_live_validated: evidenceClasses.includes("live_validated"),
  diagnostics: adapted.projection.diagnostics,
  used_unserved_envelope: mode !== "live-get",
})}\n`);

