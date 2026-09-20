import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  CANDIDATE_WINDOW_SIZE,
  STABLE_TOP_N,
} from "../src/features/first-phase-cockpit/contracts/firstPhaseEvidencePacket.ts";
import { composeCockpitViewModel } from "../src/features/first-phase-cockpit/lib/composeCockpitViewModel.ts";
import { filterCandidates } from "../src/features/first-phase-cockpit/lib/filterCandidates.ts";
import { windowCandidates } from "../src/features/first-phase-cockpit/lib/windowCandidates.ts";

const SIZES = [1000, 5000, 10000];
const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);

function normalizeRenderModel(rows, state) {
  return {
    state,
    candidate_ids_in_order: rows.map((row) => row.candidateId),
    candidate_count: rows.length,
    read_only: true,
    network_calls: false,
  };
}

function normalizeExport(rows) {
  return rows.map((row) => ({
    candidate_id: row.candidateId,
    title: row.title,
    rank_index: row.rankIndex,
    evidence_class: row.evidenceClass,
    risk_level: row.riskLevel,
    commercial_decision: row.commercialDecision,
    next_best_action: row.nextBestAction,
    is_top_candidate: row.isTopCandidate,
  }));
}

function makeBenchmark(size) {
  const risks = ["high", "medium", "low", "unknown"];
  const candidates = [];
  for (let index = 0; index < size; index += 1) {
    candidates.push({
      candidate: {
        candidate_id: `cand-${String(index).padStart(5, "0")}`,
        title: `Sanitized candidate ${index}`,
      },
      evidence_completeness: 0.2,
      risk_level: risks[index % risks.length],
      commercial_decision: "hold",
      next_best_action: "review_evidence",
    });
  }
  return {
    evidence_mode: "unknown",
    top_candidate_id: candidates[0].candidate.candidate_id,
    candidates,
    warnings: [],
    read_only: true,
    next_best_action: "review_evidence",
  };
}

function makeSanitizedFixture(size) {
  const risks = ["high", "medium", "low", "unknown"];
  const decisions = ["hold", "investigate", "defer", "blocked"];
  const rows = [];
  for (let index = 0; index < size; index += 1) {
    rows.push({
      candidateId: `cand-${String(index).padStart(5, "0")}`,
      title: `Sanitized candidate ${index}`,
      sku: null,
      rankIndex: index,
      riskLevel: risks[index % risks.length],
      commercialDecision: decisions[index % decisions.length],
      nextBestAction: "review_evidence",
      evidenceClass: "fixture",
      promotionState: "hold",
      isTopCandidate: index === 0,
    });
  }
  return Object.freeze(rows);
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function time(fn) {
  const started = process.hrtime.bigint();
  const result = fn();
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  return { result, elapsedMs };
}

test("deterministic large-list cockpit benchmark preserves order and replay hashes", async () => {
  const timings = {};
  const emptyFilter = {
    query: "",
    risk: "all",
    decision: "all",
    topOnly: false,
    topN: false,
  };
  for (const size of SIZES) {
    const fixture = makeSanitizedFixture(size);
    const firstIds = fixture.map((row) => row.candidateId);

    const normalized = time(() => normalizeRenderModel(fixture, "success"));
    assert.deepEqual(normalized.result.candidate_ids_in_order, firstIds);
    assert.equal(normalized.result.candidate_count, size);

    const filtered = time(() =>
      filterCandidates(fixture, {
        ...emptyFilter,
        risk: "high",
      }),
    );
    assert.ok(filtered.result.every((row) => row.riskLevel === "high"));
    const filteredIds = filtered.result.map((row) => row.candidateId);
    assert.deepEqual(
      filteredIds,
      firstIds.filter((_, index) => index % 4 === 0),
    );

    const windowed = time(() => windowCandidates(filtered.result, 0, CANDIDATE_WINDOW_SIZE));
    assert.equal(windowed.result.visible.length, Math.min(CANDIDATE_WINDOW_SIZE, filtered.result.length));
    assert.deepEqual(
      windowed.result.visible.map((row) => row.candidateId),
      filteredIds.slice(0, CANDIDATE_WINDOW_SIZE),
    );

    const composed = time(() =>
      composeCockpitViewModel({
        phase1Readiness: { overall_status: "ready" },
        benchmark: makeBenchmark(size),
        publicMarket: null,
        researchPortfolio: null,
        readinessError: false,
        benchmarkError: false,
        publicMarketError: false,
        researchError: false,
        isLoading: false,
      }),
    );
    assert.equal(composed.result.rankedCandidates.length, size);
    assert.deepEqual(
      composed.result.rankedCandidates.map((row) => row.candidateId),
      firstIds,
    );
    assert.notEqual(composed.result.state, "success");
    assert.notEqual(composed.result.rankedCandidates[0].evidenceClass, "live_validated");
    const exported = time(() => normalizeExport(fixture));
    assert.equal(exported.result.length, size);
    assert.equal(exported.result[0].rank_index, 0);
    assert.equal(exported.result.at(-1).rank_index, size - 1);
    assert.doesNotMatch(JSON.stringify(exported.result), /prompt|formula|heuristic|password/);

    const replayA = digest({
      ids: firstIds,
      filtered: filteredIds,
      window: windowed.result.visible.map((row) => row.candidateId),
      export: exported.result,
    });
    const replayB = digest({
      ids: fixture.map((row) => row.candidateId),
      filtered: filterCandidates(fixture, { ...emptyFilter, risk: "high" }).map((row) => row.candidateId),
      window: windowCandidates(
        filterCandidates(fixture, { ...emptyFilter, risk: "high" }),
        0,
        CANDIDATE_WINDOW_SIZE,
      ).visible.map((row) => row.candidateId),
      export: normalizeExport(fixture),
    });
    assert.equal(replayA, replayB);

    const topN = filterCandidates(fixture, { ...emptyFilter, topN: true });
    assert.equal(topN.length, STABLE_TOP_N);
    assert.deepEqual(
      topN.map((row) => row.candidateId),
      firstIds.slice(0, STABLE_TOP_N),
    );

    const render = time(() => normalizeRenderModel(windowed.result.visible, composed.result.state));
    timings[size] = {
      normalize_ms: Number(normalized.elapsedMs.toFixed(3)),
      filter_ms: Number(filtered.elapsedMs.toFixed(3)),
      window_ms: Number(windowed.elapsedMs.toFixed(3)),
      compose_ms: Number(composed.elapsedMs.toFixed(3)),
      render_model_ms: Number(render.elapsedMs.toFixed(3)),
      export_ms: Number(exported.elapsedMs.toFixed(3)),
      replay_sha256: replayA,
    };
  }

  process.stdout.write(`${JSON.stringify({ cockpit_perf_benchmark: timings }, null, 2)}\n`);

  const composeSource = await readFile(new URL("lib/composeCockpitViewModel.ts", featureRoot), "utf8");
  const filterSource = await readFile(new URL("lib/filterCandidates.ts", featureRoot), "utf8");
  const windowSource = await readFile(new URL("lib/windowCandidates.ts", featureRoot), "utf8");
  assert.match(composeSource, /commerce\.accepted/);
  assert.match(composeSource, /commerce\.rows\.map\(enrichDecisionReview\)/);
  assert.doesNotMatch(filterSource, /\.sort\(/);
  assert.match(filterSource, /if \(filter\.topN && candidate\.rankIndex >= STABLE_TOP_N\) break;/);
  assert.doesNotMatch(windowSource, /\.sort\(/);
});
