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
import {
  MAX_APPROVAL_LEDGER_REPORT_BYTES,
  validateAndParseApprovalLedgerJson,
} from "../src/features/companyos-approval-ledger-review/lib/loadLocalApprovalLedgerReport.ts";
import { safeDisplayText } from "../src/features/companyos-approval-ledger-review/lib/safeText.ts";

function viewOf(packet, extra = {}, adaptOptions = {}) {
  const adapted = adaptApprovalLedger(packet, adaptOptions);
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
  assert.equal(adapted.model.availability, "fixture");
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

test("local import source marks availability and forces execution_authorized false", () => {
  const packet = buildApprovalLedgerFixture();
  packet.execution_authorized = true;
  const adapted = adaptApprovalLedger(packet, { source: "local_file" });
  assert.equal(adapted.rejected, false);
  assert.equal(adapted.model.availability, "local_import");
  assert.equal(adapted.model.execution_authorized, false);
  assert.match(adapted.model.limitations[0], /browser memory only/i);
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

test("local JSON loader validates size shape and version without echoing contents", () => {
  const good = buildApprovalLedgerFixture();
  const text = JSON.stringify(good);
  const ok = validateAndParseApprovalLedgerJson(text, { fileName: "approval_ledger_report.json" });
  assert.equal(ok.ok, true);
  if (ok.ok) {
    assert.equal(ok.packet.report_version, "companyos-approval-ledger-v1");
    assert.equal(ok.fileName, "approval_ledger_report.json");
  }

  const notJson = validateAndParseApprovalLedgerJson("{not-json sk-live-SHOULD-NOT-ECHO", {
    fileName: "bad.json",
  });
  assert.equal(notJson.ok, false);
  if (!notJson.ok) {
    assert.equal(notJson.code, "not_json");
    assert.doesNotMatch(notJson.message, /sk-live|SHOULD-NOT-ECHO|\{not-json/i);
  }

  const wrongVersion = validateAndParseApprovalLedgerJson(
    JSON.stringify({ report_version: "other-v0", requests: [] }),
    { fileName: "wrong.json" },
  );
  assert.equal(wrongVersion.ok, false);
  if (!wrongVersion.ok) {
    assert.equal(wrongVersion.code, "unsupported_version");
    assert.doesNotMatch(wrongVersion.message, /other-v0/);
  }

  const oversized = validateAndParseApprovalLedgerJson("{}", {
    byteLength: MAX_APPROVAL_LEDGER_REPORT_BYTES + 1,
    fileName: "big.json",
  });
  assert.equal(oversized.ok, false);
  if (!oversized.ok) {
    assert.equal(oversized.code, "too_large");
  }

  const empty = validateAndParseApprovalLedgerJson("   ", { fileName: "empty.json" });
  assert.equal(empty.ok, false);
  if (!empty.ok) {
    assert.equal(empty.code, "empty_file");
  }

  const arrayRoot = validateAndParseApprovalLedgerJson("[]", { fileName: "arr.json" });
  assert.equal(arrayRoot.ok, false);
  if (!arrayRoot.ok) {
    assert.equal(arrayRoot.code, "not_object");
  }
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
  assert.equal(moveSelection(ids, "seed-manual-import", "End"), "seed-publish");
  assert.equal(moveSelection(ids, "seed-publish", "ArrowUp"), "seed-manual-import");

  const component = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/components/ApprovalLedgerReview.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(component, /onClick=\{[^}]*approve|decideApproval|create_pending_approval|fetch\(|httpx|openai/i);
  assert.doesNotMatch(component, /type="password"|name="api_key"|<form/i);
  assert.match(component, /no approve, deny, publish, spend, order, payment, messaging, or provider action controls/i);
  assert.match(component, /Evidence references/i);
  assert.match(component, /Conditions/i);
  assert.match(component, /Decision class/i);
  assert.match(component, /Not live authority/i);
  assert.match(component, /would_auto_allow_draft|humanizeToken\(item\.result\)/i);

  const featureRoot = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/INTEGRATION.md", import.meta.url),
    "utf8",
  );
  assert.match(featureRoot, /no mounted read-only HTTP GET/i);
  assert.match(featureRoot, /\/api\/cockpit\/approvals/);
  assert.match(featureRoot, /execution-cockpit write\/decide path/i);
  assert.match(featureRoot, /\/operator\/approval-ledger/);
  assert.match(featureRoot, /in memory only/i);
  assert.match(featureRoot, /local JSON report/i);
});

test("Shell router mounts /operator/approval-ledger without cockpit or mutation APIs", async () => {
  const main = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  assert.match(
    main,
    /import\s+\{\s*ApprovalLedgerReviewPage\s*\}\s+from\s+["']\.\/features\/companyos-approval-ledger-review["']/,
  );
  assert.match(
    main,
    /path:\s*["']\/operator\/approval-ledger["'],\s*element:\s*<ApprovalLedgerReviewPage\s*\/>/,
  );
  assert.doesNotMatch(main, /\/api\/cockpit\/approvals/);
  assert.doesNotMatch(main, /decideApproval|create_pending_approval/);

  const page = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/ApprovalLedgerReviewPage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /buildApprovalLedgerFixture/);
  assert.match(page, /readLocalApprovalLedgerFile/);
  assert.match(page, /type="file"/);
  assert.match(page, /Use demo fixture/);
  assert.match(page, /adaptApprovalLedger/);
  assert.doesNotMatch(page, /fetch\(|axios|httpx|\/api\//i);
  assert.doesNotMatch(page, /localStorage|indexedDB|sessionStorage/i);
  assert.doesNotMatch(page, /denyApproval|decideApproval|create_pending_approval/i);

  const loader = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/lib/loadLocalApprovalLedgerReport.ts", import.meta.url),
    "utf8",
  );
  assert.match(loader, /MAX_APPROVAL_LEDGER_REPORT_BYTES/);
  assert.doesNotMatch(loader, /fetch\(|XMLHttpRequest|localStorage/i);

  const index = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/index.ts", import.meta.url),
    "utf8",
  );
  assert.match(index, /ApprovalLedgerReviewPage/);
  assert.match(index, /readLocalApprovalLedgerFile/);
});

test("success view exposes evidence, conditions, and policy labels without authority", () => {
  const packet = buildApprovalLedgerFixture();
  const view = viewOf(packet, { selectedApprovalId: "seed-manual-import" });
  assert.equal(view.state, "success");
  assert.ok(view.selectedRequest);
  assert.equal(view.selectedRequest.approval_id, "seed-manual-import");
  assert.ok(view.selectedRequest.evidence.some((item) => item.ref_id === "ev-manual-import-1" && item.sanitized));
  assert.ok(view.selectedRequest.conditions.some((item) => /source is public/i.test(item.description)));
  assert.ok(view.model.policies.some((item) => item.decision_class === "blocked_in_current_mode"));
  assert.ok(view.model.policies.some((item) => item.decision_class === "approval_possible_later"));
  assert.equal(view.model.execution_authorized, false);
  assert.match(view.authorityNote, /do not authorize/i);
  assert.equal(view.model.simulations[0].result, "would_auto_allow_draft");
});

test("accepted local JSON still fails closed through adapter for secrets", () => {
  const packet = buildApprovalLedgerFixture();
  packet.requests[0].request_title = "leak sk-live-abcdefghijklmnopqrstuv";
  const text = JSON.stringify(packet);
  const loaded = validateAndParseApprovalLedgerJson(text, { fileName: "leaky.json" });
  // Version/shape pass; secret rejection is the adapter's job (fail closed, no echo).
  assert.equal(loaded.ok, true);
  if (loaded.ok) {
    const adapted = adaptApprovalLedger(loaded.packet, { source: "local_file" });
    assert.equal(adapted.rejected, true);
    assert.equal(adapted.reason, "prohibited_field");
    assert.equal(adapted.model.execution_authorized, false);
    assert.doesNotMatch(adapted.model.safety_summary.summary, /sk-live/);
  }
});

test("source swap clears selection identity so prior request ids cannot stick", async () => {
  const component = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/components/ApprovalLedgerReview.tsx", import.meta.url),
    "utf8",
  );
  assert.match(component, /setSelected\(null\)/);
  assert.match(component, /adaptSource,\s*packet/);

  const page = await readFile(
    new URL("../src/features/companyos-approval-ledger-review/ApprovalLedgerReviewPage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /aria-busy=\{loading/);
});

test("simulation flags never flip execution_authorized", () => {
  const packet = buildApprovalLedgerFixture();
  packet.simulations = [
    {
      ...packet.simulations[0],
      can_be_approved_now: true,
      result: "would_auto_allow_draft",
    },
  ];
  packet.execution_authorized = true;
  const adapted = adaptApprovalLedger(packet, { source: "local_file" });
  assert.equal(adapted.rejected, false);
  assert.equal(adapted.model.execution_authorized, false);
  assert.equal(adapted.model.simulations[0].can_be_approved_now, true);
  const view = viewOf(packet, {}, { source: "local_file" });
  assert.equal(view.model.execution_authorized, false);
  assert.match(view.authorityNote, /do not authorize/i);
});

test("canonical CLI artifact imports via File API as local in-memory report", async () => {
  const { mkdtempSync, readFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { spawnSync } = await import("node:child_process");
  const { fileURLToPath } = await import("node:url");

  const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
  const outDir = mkdtempSync(join(tmpdir(), "approval-ledger-cli-"));
  try {
    const script = join(repoRoot, "scripts/run_companyos_approval_ledger.py");
    const run = spawnSync("python3", [script, "--simulate-action", "model_spend", "--requested-budget", "0", "--output", outDir], {
      encoding: "utf8",
      cwd: repoRoot,
    });
    assert.equal(run.status, 0, run.stderr || run.stdout || "CLI failed");
    const reportPath = join(outDir, "approval_ledger_report.json");
    const text = readFileSync(reportPath, "utf8");
    const file = new File([text], "approval_ledger_report.json", { type: "application/json" });
    const { readLocalApprovalLedgerFile } = await import(
      "../src/features/companyos-approval-ledger-review/lib/loadLocalApprovalLedgerReport.ts"
    );
    const loaded = await readLocalApprovalLedgerFile(file);
    assert.equal(loaded.ok, true);
    if (!loaded.ok) return;
    assert.equal(loaded.fileName, "approval_ledger_report.json");
    assert.equal(loaded.packet.report_version, "companyos-approval-ledger-v1");

    const adapted = adaptApprovalLedger(loaded.packet, { source: "local_file" });
    assert.equal(adapted.rejected, false);
    assert.equal(adapted.model.availability, "local_import");
    assert.equal(adapted.model.execution_authorized, false);
    assert.ok(adapted.model.requests.length >= 1);
    assert.match(adapted.model.limitations[0], /browser memory only/i);

    const view = viewOf(loaded.packet, {}, { source: "local_file" });
    assert.equal(view.state, "success");
    assert.equal(view.model.execution_authorized, false);
    assert.match(view.authorityNote, /do not authorize/i);
  } finally {
    rmSync(outDir, { recursive: true, force: true });
  }
});

test("source swap drops prior selected id when reports share an approval_id", () => {
  const demo = buildApprovalLedgerFixture();
  const local = structuredClone(demo);
  local.requests = [
    { ...demo.requests[1], approval_id: "shared-id", request_title: "Local first" },
    { ...demo.requests[0], approval_id: "seed-manual-import", request_title: "Local second" },
  ];
  // Operator had selected the shared id on the demo report.
  const before = viewOf(demo, { selectedApprovalId: "seed-manual-import" });
  assert.equal(before.selectedApprovalId, "seed-manual-import");
  // Page clears selection to null on source swap; compose then defaults to the new report's first id.
  const after = viewOf(local, { selectedApprovalId: null }, { source: "local_file" });
  assert.equal(after.model.availability, "local_import");
  assert.equal(after.selectedApprovalId, "shared-id");
  assert.notEqual(after.selectedApprovalId, "seed-manual-import");
});
