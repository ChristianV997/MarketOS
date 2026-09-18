import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const matrixRoot = new URL("../src/features/first-phase-cockpit/fixtures/projection-matrix/", import.meta.url);
const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);

const SECRET_SHAPED = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;
const FORBIDDEN_EXPORT_KEY = /prompt|formula|heuristic|source_code|private_key|provider_payload|internal_notes/;
const PATH_SHAPED = /(^|[\\/])(users|home|documents|marketos)[\\/]/i;

function containsSecretShapedValue(value) {
  if (typeof value === "string") return SECRET_SHAPED.test(value) || PATH_SHAPED.test(value);
  if (Array.isArray(value)) return value.some(containsSecretShapedValue);
  if (value && typeof value === "object") {
    return Object.entries(value).some(([key, item]) => {
      const keyL = key.toLowerCase().replace(/-/g, "_");
      if (FORBIDDEN_EXPORT_KEY.test(keyL) || keyL.includes("password") || keyL.includes("secret") || keyL.includes("api_key")) {
        return true;
      }
      return containsSecretShapedValue(item);
    });
  }
  return false;
}

function optionalNumber(record, key) {
  if (!record || !(key in record)) return null;
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function indexUnique(audits) {
  const byId = new Map();
  for (const audit of audits) {
    if (!audit || typeof audit.candidate_id !== "string" || !audit.candidate_id.trim()) {
      return { ok: false, reason: "candidate_identity_missing" };
    }
    if (byId.has(audit.candidate_id)) return { ok: false, reason: "candidate_identity_duplicate" };
    byId.set(audit.candidate_id, audit);
  }
  return { ok: true, byId };
}

function validateProjection(raw) {
  if (!raw || typeof raw !== "object") return { ok: false, reason: "projection_not_object" };
  if (containsSecretShapedValue(raw)) return { ok: false, reason: "secret_shaped_value_rejected" };
  if (raw.report_version !== "product-validation-report-v1") return { ok: false, reason: "schema_version_unsupported" };
  const appendix = raw.appendix;
  if (!appendix || typeof appendix !== "object") return { ok: false, reason: "appendix_required" };
  if (appendix.research_to_decision_version !== "v1") return { ok: false, reason: "schema_version_unsupported" };
  if (appendix.candidate_audit !== undefined && !Array.isArray(appendix.candidate_audit)) {
    return { ok: false, reason: "candidate_audit_malformed" };
  }
  if (appendix.client_safe_projection?.launch_authorized === true) {
    return { ok: false, reason: "launch_authorized_rejected" };
  }
  const auditCount = Array.isArray(appendix.candidate_audit) ? appendix.candidate_audit.length : 0;
  if (auditCount > 200) return { ok: false, reason: "projection_oversized" };
  if (Array.isArray(appendix.candidate_audit)) {
    const indexed = indexUnique(appendix.candidate_audit);
    if (!indexed.ok) return indexed;
  }
  return { ok: true, packet: raw };
}

function adapt(rows, raw) {
  const validated = validateProjection(raw);
  if (!validated.ok) {
    return { rows, warning: validated.reason, accepted: false, unmatchedServerIds: [], unmatchedProjectionIds: [] };
  }
  const audits = validated.packet.appendix.candidate_audit ?? [];
  const safe = validated.packet.appendix.client_safe_projection?.candidates ?? [];
  if (!audits.length && !safe.length) {
    return { rows, warning: null, accepted: true, unmatchedServerIds: [], unmatchedProjectionIds: [] };
  }
  const auditIndex = indexUnique(audits);
  const safeIndex = indexUnique(safe);
  if (!auditIndex.ok) return { rows, warning: auditIndex.reason, accepted: false, unmatchedServerIds: [], unmatchedProjectionIds: [] };
  if (!safeIndex.ok) return { rows, warning: safeIndex.reason, accepted: false, unmatchedServerIds: [], unmatchedProjectionIds: [] };
  const projectionIds = new Set([...auditIndex.byId.keys(), ...safeIndex.byId.keys()]);
  const unmatchedServerIds = [];
  const matched = new Set();
  const next = rows.map((row) => {
    const audit = { ...(safeIndex.byId.get(row.candidateId) || {}), ...(auditIndex.byId.get(row.candidateId) || {}) };
    if (!audit.candidate_id && !auditIndex.byId.has(row.candidateId) && !safeIndex.byId.has(row.candidateId)) {
      unmatchedServerIds.push(row.candidateId);
      return row;
    }
    matched.add(row.candidateId);
    const offer = (audit.supplier_offers || []).find((item) => item.status !== "quarantined");
    return {
      ...row,
      sku: offer?.exact_sku ?? audit.sku ?? null,
      confidence: optionalNumber(audit.confidence, "overall"),
      confidenceSupplier: optionalNumber(audit.confidence, "supplier"),
      economicsUnavailable: !audit.economics || Object.keys(audit.economics).length === 0,
      freshness: audit.freshness ?? null,
      riskLevel: audit.risk_state ?? row.riskLevel,
    };
  });
  return {
    rows: next,
    warning: null,
    accepted: true,
    unmatchedServerIds,
    unmatchedProjectionIds: [...projectionIds].filter((id) => !matched.has(id)),
  };
}

async function loadFixture(name) {
  return JSON.parse(await readFile(new URL(name, matrixRoot), "utf8"));
}

test("accepted #247-shaped screening projection maps by candidate_id without averaging confidence", async () => {
  const packet = await loadFixture("accepted-manual-screening.json");
  assert.equal(validateProjection(packet).ok, true);
  const rows = [
    { candidateId: "hydroponics-kit", rankIndex: 0, sku: null, riskLevel: "medium" },
    { candidateId: "server-only", rankIndex: 1, sku: null, riskLevel: "low" },
  ];
  const adapted = adapt(rows, packet);
  assert.equal(adapted.accepted, true);
  assert.deepEqual(adapted.rows.map((row) => row.candidateId), ["hydroponics-kit", "server-only"]);
  assert.equal(adapted.rows[0].sku, "HYDRO-KIT-01");
  assert.equal(adapted.rows[0].confidence, null);
  assert.equal(adapted.rows[0].confidenceSupplier, 0.4);
  assert.equal(adapted.rows[0].economicsUnavailable, false);
  assert.deepEqual(adapted.unmatchedServerIds, ["server-only"]);
  assert.equal(adapted.rows[1].sku, null);
});

test("projection matrix rejects unsupported, duplicate, secret, malformed, and launch-authorized packets", async () => {
  assert.equal((await validateProjection(await loadFixture("rejected-unsupported-version.json"))).reason, "schema_version_unsupported");
  assert.equal((await validateProjection(await loadFixture("rejected-duplicate-ids.json"))).reason, "candidate_identity_duplicate");
  assert.equal((await validateProjection(await loadFixture("rejected-secret.json"))).reason, "secret_shaped_value_rejected");
  assert.equal((await validateProjection(await loadFixture("rejected-malformed.json"))).reason, "candidate_audit_malformed");
  assert.equal((await validateProjection(await loadFixture("rejected-launch-authorized.json"))).reason, "launch_authorized_rejected");
  assert.equal(
    validateProjection({
      report_version: "product-validation-report-v1",
      appendix: { research_to_decision_version: "v1", candidate_audit: [{ title: "missing-id" }] },
    }).reason,
    "candidate_identity_missing",
  );
});

test("partial appendix is accepted and extra fields are ignored", async () => {
  const packet = await loadFixture("partial-appendix.json");
  assert.equal(validateProjection(packet).ok, true);
  const adapted = adapt([{ candidateId: "alpha", rankIndex: 0, sku: "KEEP" }], packet);
  assert.equal(adapted.accepted, true);
  assert.equal(adapted.rows[0].sku, "KEEP");
});

test("stale report rows without server matches are not inserted", async () => {
  const packet = await loadFixture("stale-unmatched.json");
  const adapted = adapt(
    [{ candidateId: "hydroponics-kit", rankIndex: 0, sku: null, riskLevel: "medium" }],
    packet,
  );
  assert.equal(adapted.accepted, true);
  assert.equal(adapted.rows.length, 1);
  assert.equal(adapted.rows[0].freshness, "expired");
  assert.equal(adapted.rows[0].riskLevel, "blocked");
  assert.equal(adapted.rows[0].economicsUnavailable, true);
  assert.deepEqual(adapted.unmatchedProjectionIds, ["report-only-row"]);
});

test("unavailable confidence is not coerced to zero", () => {
  assert.equal(optionalNumber({}, "overall"), null);
  assert.equal(optionalNumber({ overall: 0 }, "overall"), 0);
  assert.equal(optionalNumber({ overall: null }, "overall"), null);
});

test("oversized candidate audits are rejected", () => {
  const packet = {
    report_version: "product-validation-report-v1",
    appendix: {
      research_to_decision_version: "v1",
      candidate_audit: Array.from({ length: 201 }, (_, index) => ({ candidate_id: `c-${index}` })),
    },
  };
  assert.equal(validateProjection(packet).reason, "projection_oversized");
});

test("adapter source remains identity-preserving and fail-closed", async () => {
  const source = await readFile(new URL("lib/overlayResearchToDecision.ts", featureRoot), "utf8");
  assert.match(source, /adaptResearchToDecisionProjection/);
  assert.match(source, /candidate_identity_duplicate/);
  assert.match(source, /candidate_identity_missing/);
  assert.match(source, /launch_authorized_rejected/);
  assert.match(source, /projection_oversized/);
  assert.match(source, /optionalNumber/);
  assert.match(source, /Never coerce null to 0/);
  assert.doesNotMatch(source, /\.sort\(/);
  assert.doesNotMatch(source, /\(supplier \+ market\) \/ 2/);
});
