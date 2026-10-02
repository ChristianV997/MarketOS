import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  OWNER_PERFORMANCE_API_PATH,
  OWNER_PERFORMANCE_SCHEMA,
  CONTRACT_HEAD,
  MEASURE_KEYS,
} from "../src/features/owner-performance/contracts/ownerPerformanceReport.ts";
import {
  DEMO_OBSERVED_REPORT,
  DEMO_PARTIAL_REPORT,
} from "../src/features/owner-performance/fixtures/demoReport.ts";
import {
  fetchOwnerPerformanceReport,
  OwnerPerformanceAuthError,
  OwnerPerformanceUnavailableError,
  OwnerPerformanceApiError,
} from "../src/features/owner-performance/lib/fetchOwnerPerformance.ts";
import {
  assertReportContract,
  isExplicitZero,
  presentCampaigns,
  presentMeasure,
  presentMeasures,
  reportHasFixtureEvidence,
  textSummary,
} from "../src/features/owner-performance/lib/presentReport.ts";

test("contract head and canonical API path constants are pinned", () => {
  assert.equal(OWNER_PERFORMANCE_SCHEMA, "owner-performance-report-v1");
  assert.equal(CONTRACT_HEAD, "17f0c6caa769ea13a3635b28dbb70313802da2fa");
  assert.equal(OWNER_PERFORMANCE_API_PATH, "/api/owner/performance");
});

test("fetch client calls GET /api/owner/performance without workspace selector", async () => {
  let interceptedUrl = "";
  let interceptedInit = null;

  const mockFetch = async (url, init) => {
    interceptedUrl = String(url);
    interceptedInit = init;
    return new Response(JSON.stringify(DEMO_OBSERVED_REPORT), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const report = await fetchOwnerPerformanceReport(mockFetch);
  assert.equal(report.schema, "owner-performance-report-v1");
  assert.match(interceptedUrl, /\/api\/owner\/performance$/);
  assert.doesNotMatch(interceptedUrl, /workspace/);
  assert.equal(interceptedInit?.method, "GET");
});

test("fetch client maps HTTP 404 to fail-closed unavailable citing PR #368 dependency", async () => {
  const mockFetch = async () => new Response("Not Found", { status: 404 });

  await assert.rejects(
    async () => fetchOwnerPerformanceReport(mockFetch),
    (err) => {
      assert.ok(err instanceof OwnerPerformanceUnavailableError);
      assert.equal(err.status, 404);
      assert.match(err.message, /owner-performance-report-v1/);
      assert.match(err.message, /PR #368/);
      return true;
    }
  );
});

test("fetch client maps HTTP 503 and network failure to unavailable", async () => {
  const mock503Fetch = async () => new Response("Service Unavailable", { status: 503 });
  await assert.rejects(
    async () => fetchOwnerPerformanceReport(mock503Fetch),
    (err) => {
      assert.ok(err instanceof OwnerPerformanceUnavailableError);
      assert.equal(err.status, 503);
      return true;
    }
  );

  const mockNetFailFetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  await assert.rejects(
    async () => fetchOwnerPerformanceReport(mockNetFailFetch),
    (err) => {
      assert.ok(err instanceof OwnerPerformanceUnavailableError);
      assert.match(err.message, /Network or server unreachable/);
      return true;
    }
  );
});

test("fetch client maps HTTP 401 and 403 to OwnerPerformanceAuthError", async () => {
  for (const status of [401, 403]) {
    const mockAuthFetch = async () => new Response("Unauthorized", { status });
    await assert.rejects(
      async () => fetchOwnerPerformanceReport(mockAuthFetch),
      (err) => {
        assert.ok(err instanceof OwnerPerformanceAuthError);
        assert.equal(err.status, status);
        assert.match(err.message, /Authentication is required/);
        return true;
      }
    );
  }
});

test("fetch client maps HTTP 500 to OwnerPerformanceApiError", async () => {
  const mock500Fetch = async () => new Response("Internal Server Error", { status: 500 });
  await assert.rejects(
    async () => fetchOwnerPerformanceReport(mock500Fetch),
    (err) => {
      assert.ok(err instanceof OwnerPerformanceApiError);
      assert.equal(err.status, 500);
      assert.match(err.message, /HTTP 500/);
      return true;
    }
  );
});

test("evidence labels cover observed, manual, fixture, modeled, and assumed classes", () => {
  const reportWithClasses = {
    ...DEMO_OBSERVED_REPORT,
    product_cost: {
      ...DEMO_OBSERVED_REPORT.product_cost,
      status: "assumed",
      evidence_state: "assumed",
      evidence_classes: ["assumed"],
    },
    shipping_cost: {
      ...DEMO_OBSERVED_REPORT.shipping_cost,
      status: "manual",
      evidence_state: "manual",
      evidence_classes: ["manual"],
    },
    fees: {
      ...DEMO_OBSERVED_REPORT.fees,
      status: "modeled",
      evidence_state: "modeled",
      evidence_classes: ["modeled"],
    },
    ad_spend: {
      ...DEMO_OBSERVED_REPORT.ad_spend,
      status: "fixture",
      evidence_state: "fixture",
      evidence_classes: ["fixture"],
    },
    evidence_quality: {
      ...DEMO_OBSERVED_REPORT.evidence_quality,
      evidence_classes: ["assumed", "fixture", "manual", "modeled", "observed"],
    },
  };

  const measures = presentMeasures(reportWithClasses);
  const byKey = Object.fromEntries(measures.map((m) => [m.key, m]));

  assert.equal(byKey.product_cost.status, "assumed");
  assert.equal(byKey.shipping_cost.status, "manual");
  assert.equal(byKey.fees.status, "modeled");
  assert.equal(byKey.ad_spend.status, "fixture");
  assert.equal(reportHasFixtureEvidence(reportWithClasses), true);
});

test("missing amounts remain Unavailable and are never coerced to numeric zero", () => {
  const missingShipping = {
    ...DEMO_OBSERVED_REPORT,
    shipping_cost: {
      status: "unavailable",
      amount: null,
      currency: null,
      provenance: "unavailable",
      evidence_state: "missing",
      missing_reason: "shipping_cost_absent",
    },
    missing_inputs: ["shipping_cost_absent"],
  };

  const presented = presentMeasure("shipping_cost", missingShipping.shipping_cost, missingShipping);
  assert.equal(presented.availability, "unavailable");
  assert.equal(presented.amountText, "Unavailable");
  assert.equal(presented.currencyText, "\u2014");
  assert.match(presented.summary, /Not zero/);
  assert.match(presented.summary, /shipping_cost_absent/);
});

test("explicit zero requires amount=0 and key in explicit_zeros list", () => {
  const fakeZero = {
    ...DEMO_OBSERVED_REPORT,
    refunds: { ...DEMO_OBSERVED_REPORT.refunds, amount: "0.00", status: "observed" },
    explicit_zeros: [], // Not declared as explicit zero!
  };
  // Not explicit zero because explicit_zeros is empty
  assert.equal(isExplicitZero("0.00", "refunds", fakeZero), false);

  const genuineZero = {
    ...DEMO_OBSERVED_REPORT,
    refunds: { ...DEMO_OBSERVED_REPORT.refunds, amount: "0.00", status: "observed" },
    explicit_zeros: ["refunds"],
  };
  assert.equal(isExplicitZero("0.00", "refunds", genuineZero), true);
  const presented = presentMeasure("refunds", genuineZero.refunds, genuineZero);
  assert.equal(presented.availability, "explicit_zero");
  assert.equal(presented.amountText, "0.00");
});

test("canonical measure ordering and campaign server ordering are strictly preserved", () => {
  const report = {
    ...DEMO_OBSERVED_REPORT,
    campaigns: [
      {
        campaign_id: "zeta-camp",
        ad_spend: { ...DEMO_OBSERVED_REPORT.ad_spend, amount: "5.00" },
        attributed_revenue: { ...DEMO_OBSERVED_REPORT.revenue, amount: "10.00" },
        lift: { status: "unavailable", amount: null, currency: null, provenance: "", evidence_state: "", missing_reason: "causal_lift_unsupported" },
        causal_attribution: false,
      },
      {
        campaign_id: "alpha-camp",
        ad_spend: { ...DEMO_OBSERVED_REPORT.ad_spend, amount: "50.00" },
        attributed_revenue: { ...DEMO_OBSERVED_REPORT.revenue, amount: "100.00" },
        lift: { status: "unavailable", amount: null, currency: null, provenance: "", evidence_state: "", missing_reason: "causal_lift_unsupported" },
        causal_attribution: false,
      },
    ],
  };

  const measures = presentMeasures(report);
  assert.deepEqual(
    measures.map((m) => m.key),
    [...MEASURE_KEYS]
  );

  const campaigns = presentCampaigns(report);
  // Must preserve incoming server array order (zeta-camp first, alpha-camp second) without re-ranking
  assert.equal(campaigns[0].campaignId, "zeta-camp");
  assert.equal(campaigns[1].campaignId, "alpha-camp");
});

test("safety guards reject authority escalation in assertReportContract", () => {
  const launchAuthorized = { ...DEMO_OBSERVED_REPORT, safety: { ...DEMO_OBSERVED_REPORT.safety, launch_authorized: true } };
  assert.throws(() => assertReportContract(launchAuthorized), /launch_authorized_rejected/);

  const adsLaunched = { ...DEMO_OBSERVED_REPORT, safety: { ...DEMO_OBSERVED_REPORT.safety, ads_launched: true } };
  assert.throws(() => assertReportContract(adsLaunched), /ads_launched_rejected/);

  const publishing = { ...DEMO_OBSERVED_REPORT, safety: { ...DEMO_OBSERVED_REPORT.safety, publishing: true } };
  assert.throws(() => assertReportContract(publishing), /publishing_rejected/);

  const liftClaimed = {
    ...DEMO_OBSERVED_REPORT,
    evidence_quality: {
      ...DEMO_OBSERVED_REPORT.evidence_quality,
      claims: { ...DEMO_OBSERVED_REPORT.evidence_quality.claims, campaign_lift: true },
    },
  };
  assert.throws(() => assertReportContract(liftClaimed), /lift_claim_rejected/);

  const notReadOnly = {
    ...DEMO_OBSERVED_REPORT,
    safety: { ...DEMO_OBSERVED_REPORT.safety, read_only: false },
  };
  assert.throws(() => assertReportContract(notReadOnly), /read_only_required/);

  const campaignAttributionClaimed = {
    ...DEMO_OBSERVED_REPORT,
    campaigns: [{ ...DEMO_OBSERVED_REPORT.campaigns[0], causal_attribution: true }],
  };
  assert.throws(() => assertReportContract(campaignAttributionClaimed), /campaign_attribution_claim_rejected/);

  const campaignLiftClaimed = {
    ...DEMO_OBSERVED_REPORT,
    campaigns: [{
      ...DEMO_OBSERVED_REPORT.campaigns[0],
      lift: { status: "observed", amount: "10.00", currency: "USD", provenance: "observed", evidence_state: "observed", missing_reason: null },
    }],
  };
  assert.throws(() => assertReportContract(campaignLiftClaimed), /campaign_lift_claim_rejected/);
});

test("dashboard component source preserves accessibility and mobile responsive contracts", async () => {
  const source = await readFile(
    new URL("../src/features/owner-performance/components/OwnerPerformanceDashboard.tsx", import.meta.url),
    "utf8"
  );

  // Table accessibility & roving tabindex
  assert.match(source, /<caption/);
  assert.match(source, /role="grid"/);
  assert.match(source, /scope="col"/);
  assert.match(source, /scope="row"/);
  assert.match(source, /aria-selected/);
  assert.match(source, /onKeyDown/);
  assert.match(source, /rowRefs/);
  assert.match(source, /aria-pressed/);

  // Status notes & alert roles
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, /aria-live="polite"/);

  // Accessible chart patterns (distinguishable without color alone) & legend
  assert.match(source, /spend-stripes/);
  assert.match(source, /revenue-dots/);
  assert.match(source, /fill="url\(#spend-stripes\)"/);
  assert.match(source, /fill="url\(#revenue-dots\)"/);
  assert.match(source, /<Legend/);
  assert.match(source, /Visual comparison/);

  // Mobile responsiveness
  assert.match(source, /grid-cols-1 sm:grid-cols-2 lg:grid-cols-4/);
  assert.match(source, /min-w-0/);

  // Distinct states
  assert.match(source, /tone="unavailable"/);
  assert.match(source, /tone="empty"/);
  assert.match(source, /tone="stale"/);
  assert.match(source, /Authentication required/);

  // Separation of concerns: no direct fetch in component
  assert.doesNotMatch(source, /fetch\(/);
});
