import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptApprovalLedger } from "../src/features/companyos-approval-ledger-review/lib/adaptApprovalLedger.ts";
import {
  composeApprovalLedgerView,
  moveSelection,
  requestIds,
} from "../src/features/companyos-approval-ledger-review/lib/composeApprovalLedgerView.ts";
import { buildApprovalLedgerFixture } from "../src/features/companyos-approval-ledger-review/fixtures/ledgerFixture.ts";
import { safeDisplayText } from "../src/features/companyos-approval-ledger-review/lib/safeText.ts";

function viewOf(packet, extra = {}) {
  const adapted = adaptApprovalLedger(packet);
  return composeApprovalLedgerView({
    loading: false,
    errorMessage: null,
    model: adapted.model,
    rejected: adapted.rejected,
    selectedApprovalId: null,
    ...extra,
  });
}

test("fixture report adapts to success with blocked vs draft distinctions", () => {
  const packet = buildApprovalLedgerFixture();
  const adapted = adaptApprovalLedger(packet);
  assert.equal(adapted.rejected, false);
  assert.equal(adapted.model.report_version, "companyos-approval-ledger-v1");
  assert.equal(adapted.model.execution_authorized, false);
  assert.equal(adapted.model.offline_planning_only, true);
  assert.equal(adapted.model.safety_summary.read_only, true);
  assert.equal(adapted.model.safety_summary.external_action_performed, false);
  assert.equal(adapted.model.safety_summary.live_capabilities_enabled, false);

  const view = viewOf(packet);
  assert.equal(view.state, "success");
  assert.match(view.authorityNote, /do not authorize/i);

  const byId = Object.fromEntries(view.model.requests.map((item) => [item.approval_id, item]));
  assert.equal(byId["seed-manual-import"].status_bucket, "draft");
  assert.equal(byId["seed-publish"].status_bucket, "blocked");
  assert.ok(byId["seed-manual-import"].evidence.length >= 1);
  assert.equal(byId["seed-manual-import"].evidence[0].sanitized, true);
  assert.ok(view.model.policies.some((item) => item.blocked_in_current_mode));
  assert.ok(view.model.policies.some((item) => !item.blocked_in_current_mode));
  assert.equal(view.model.simulations[0].result, "would_auto_allow_draft");
  assert.equal(view.model.simulations[0].can_be_approved_now === true || view.model.simulations[0].can_be_approved_now === false, true);
});

test("loading empty and error states stay honest", () => {
  const packet = buildApprovalLedgerFixture();
  const loading = composeApprovalLedgerView({
    loading: true,
    errorMessage: null,
    model: adaptApprovalLedger(packet).model,
    rejected: false,
    selectedApprovalId: null,
  });
  assert.equal(loading.state, "loading");

  const emptyPacket = buildApprovalLedgerFixture();
  emptyPacket.requests = [];
  emptyPacket.policies = [];
  emptyPacket.approval_count = 0;
  assert.equal(viewOf(emptyPacket).state, "empty");

  const bad = adaptApprovalLedger({ report_version: "nope" });
  assert.equal(bad.rejected, true);
  const errored = composeApprovalLedgerView({
    loading: false,
    errorMessage: null,
    model: bad.model,
    rejected: true,
    selectedApprovalId: null,
  });
  assert.equal(errored.state, "error");
});

test("secret-shaped and unsafe safety summaries are rejected", () => {
  const secret = buildApprovalLedgerFixture();
  secret.requests[0].request_title = "leak sk-live-abcdefghijklmnopqrstuv";
  assert.equal(adaptApprovalLedger(secret).rejected, true);

  const keyed = buildApprovalLedgerFixture();
  keyed.api_key = "synthetic";
  assert.equal(adaptApprovalLedger(keyed).rejected, true);

  const liveClaim = buildApprovalLedgerFixture();
  liveClaim.safety_summary = {
    read_only: true,
    network_calls: false,
    mutated: false,
    external_action_performed: false,
    credentials_present: false,
    live_capabilities_enabled: true,
    policy_fail_closed: true,
    audit_trail_present: true,
    secrets_stored: false,
    summary: "tampered safety summary for rejection test",
  };
  assert.equal(adaptApprovalLedger(liveClaim).reason, "unsafe_safety_summary");
});

test("safe display strips angle brackets and control characters", () => {
  assert.equal(safeDisplayText("<script>alert(1)</script>"), "scriptalert(1)/script");
  assert.equal(safeDisplayText("ok\u0000title"), "oktitle");
});

test("keyboard selection stays in source order and source has no mutation controls", async () => {
  const packet = buildApprovalLedgerFixture();
  const ids = requestIds(adaptApprovalLedger(packet).model);
  assert.deepEqual(ids, ["seed-manual-import", "seed-publish"]);
  assert.equal(moveSelection(ids, null, "ArrowDown"), "seed-manual-import");
  assert.equal(moveSelection(ids, "seed-manual-import", "ArrowDown"), "seed-publish");
  assert.equal(moveSelection(ids, "seed-publish", "Home"), "seed-manual-import");

  const component = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/components/ApprovalLedgerReview.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(component, /onClick=\{[^}]*approve|decideApproval|create_pending_approval|fetch\(|httpx|openai/i);
  assert.doesNotMatch(component, /type="password"|name="api_key"|<form/i);
  assert.match(component, /no approve, deny, publish, spend, order, payment, messaging, or provider action controls/i);

  const featureRoot = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/INTEGRATION.md", import.meta.url),
    "utf8",
  );
  assert.match(featureRoot, /no mounted read-only HTTP GET/i);
  assert.match(featureRoot, /\/api\/cockpit\/approvals/);
  assert.match(featureRoot, /execution-cockpit write\/decide path/i);
});
