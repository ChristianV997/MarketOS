import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptConsultingResearch, normalizeEvidenceClass } from "../src/features/consulting-research-workbench/lib/adaptConsultingResearch.ts";
import { composeConsultingResearchViewModel, moveSection, sectionOrder } from "../src/features/consulting-research-workbench/lib/composeConsultingResearchViewModel.ts";
import { buildClientSafeReviewExport } from "../src/features/consulting-research-workbench/lib/exportClientSafeReview.ts";
import { buildReviewFixture } from "../src/features/consulting-research-workbench/fixtures/buildReviewFixture.ts";

test("fixture packet keeps section order and never becomes live proof", () => {
  const raw = buildReviewFixture();
  const adapted = adaptConsultingResearch(raw);
  assert.equal(adapted.rejected, false);
  assert.deepEqual(sectionOrder(adapted.review), ["demand", "customer", "competitor", "supplier", "logistics", "economics"]);
  const view = composeConsultingResearchViewModel({
    isLoading: false,
    review: adapted.review,
    rejected: false,
    selectedSectionId: null,
  });
  assert.equal(view.launchAuthorized, false);
  assert.equal(view.liveProof, false);
  assert.notEqual(view.surface, "success");
  assert.equal(view.review.confidence_label, null);
  const exported = buildClientSafeReviewExport(adapted.review);
  assert.equal(exported.accepted, true);
  assert.equal(exported.payload.live_validated, false);
  assert.equal(exported.payload.launch_authorized, false);
  const { omitted, ...body } = exported.payload;
  assert.deepEqual(omitted, [
    "internal_prompt",
    "internal_formula",
    "source_code",
    "credentials",
    "raw_provider_payload",
    "hidden_heuristics",
    "cross_client_data",
  ]);
  assert.doesNotMatch(JSON.stringify(body), /internal_prompt|internal_formula|sk-live-/);
});

test("live_validated claims normalize to unavailable and unknown confidence stays null", () => {
  assert.equal(normalizeEvidenceClass("live_validated"), "unavailable");
  assert.equal(normalizeEvidenceClass("manual_import"), "manual");
  const raw = buildReviewFixture();
  raw.sections[0].items[0].evidence_class = "live_validated";
  delete raw.confidence_label;
  const adapted = adaptConsultingResearch(raw);
  assert.equal(adapted.review.sections[0].items[0].evidence_class, "unavailable");
  assert.equal(adapted.review.confidence_label, null);
  assert.equal(adapted.review.sections[0].items[0].captured_at, null);
});

test("malformed, secret, and cross-client packets stay unavailable", () => {
  assert.equal(adaptConsultingResearch("nope").rejected, true);
  const secret = buildReviewFixture();
  secret.research_question = "sk-live-abcdefghijklmnopqrstuvwxyz";
  assert.equal(adaptConsultingResearch(secret).rejection_reason, "secret_or_cross_client_rejected");
  const leaked = buildReviewFixture();
  leaked.cross_client_notes = "other workspace";
  assert.equal(adaptConsultingResearch(leaked).rejected, true);
});

test("keyboard movement stays inside source section order", () => {
  const order = ["demand", "customer", "competitor"];
  assert.equal(moveSection(order, "demand", "ArrowDown"), "customer");
  assert.equal(moveSection(order, "customer", "End"), "competitor");
  assert.equal(moveSection(order, "competitor", "Home"), "demand");
  assert.deepEqual(moveSection(order, "demand", "ArrowUp"), "demand");
});

test("feature source stays route-independent and GET-only", async () => {
  const component = await readFile(new URL("../src/features/consulting-research-workbench/components/ConsultingResearchWorkbench.tsx", import.meta.url), "utf8");
  const hookless = await readFile(new URL("../src/features/consulting-research-workbench/index.ts", import.meta.url), "utf8");
  assert.match(component, /aria-live="polite"/);
  assert.match(component, /Skip to research sections/);
  assert.match(component, /<table/);
  assert.match(component, /motion-reduce:transition-none/);
  assert.match(component, /overflow-x-auto/);
  assert.doesNotMatch(component, /method:\s*["']POST["']/);
  assert.doesNotMatch(hookless, /\/api\//);
  assert.doesNotMatch(component, /Shell/);
});
