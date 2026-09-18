import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const WINDOW_SIZE = 50;
const STABLE_TOP_N = 10;
const SIZES = [1000, 5000, 10000];
const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);

function filterCandidates(candidates, filter) {
  const query = filter.query.trim().toLowerCase();
  const filtered = [];
  for (const candidate of candidates) {
    if (filter.topN && candidate.rankIndex >= STABLE_TOP_N) continue;
    if (filter.topOnly && !candidate.isTopCandidate) continue;
    if (filter.risk !== "all") {
      const risk = (candidate.riskLevel ?? "unknown").toLowerCase();
      if (risk !== filter.risk) continue;
    }
    if (filter.decision !== "all" && (candidate.commercialDecision ?? "") !== filter.decision) continue;
    if (query) {
      const haystack = [candidate.candidateId, candidate.title, candidate.commercialDecision]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) continue;
    }
    filtered.push(candidate);
  }
  return filtered;
}

function windowCandidates(candidates, windowStart, windowSize = WINDOW_SIZE) {
  const size = Math.max(1, windowSize);
  const start = candidates.length === 0 ? 0 : Math.min(Math.max(0, windowStart), Math.max(0, candidates.length - size));
  return candidates.slice(start, start + size);
}

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

function makeSanitizedFixture(size) {
  const risks = ["high", "medium", "low", "unknown"];
  const decisions = ["hold", "investigate", "defer", "blocked"];
  const rows = [];
  for (let index = 0; index < size; index += 1) {
    rows.push({
      candidateId: `cand-${String(index).padStart(5, "0")}`,
      title: `Sanitized candidate ${index}`,
      rankIndex: index,
      riskLevel: risks[index % risks.length],
      commercialDecision: decisions[index % decisions.length],
      nextBestAction: "review_evidence",
      evidenceClass: "fixture_screening",
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
  for (const size of SIZES) {
    const fixture = makeSanitizedFixture(size);
    const firstIds = fixture.map((row) => row.candidateId);

    const normalized = time(() => normalizeRenderModel(fixture, "success"));
    assert.deepEqual(normalized.result.candidate_ids_in_order, firstIds);
    assert.equal(normalized.result.candidate_count, size);

    const filtered = time(() =>
      filterCandidates(fixture, {
        query: "",
        risk: "high",
        decision: "all",
        topOnly: false,
        topN: false,
      }),
    );
    assert.ok(filtered.result.every((row) => row.riskLevel === "high"));
    const filteredIds = filtered.result.map((row) => row.candidateId);
    assert.deepEqual(
      filteredIds,
      firstIds.filter((_, index) => index % 4 === 0),
    );

    const windowed = time(() => windowCandidates(filtered.result, 0, WINDOW_SIZE));
    assert.equal(windowed.result.length, Math.min(WINDOW_SIZE, filtered.result.length));
    assert.deepEqual(
      windowed.result.map((row) => row.candidateId),
      filteredIds.slice(0, WINDOW_SIZE),
    );

    const render = time(() => normalizeRenderModel(windowed.result, "success"));
    const exported = time(() => normalizeExport(fixture));
    assert.equal(exported.result.length, size);
    assert.equal(exported.result[0].rank_index, 0);
    assert.equal(exported.result.at(-1).rank_index, size - 1);
    assert.doesNotMatch(JSON.stringify(exported.result), /prompt|formula|heuristic|password/);

    const replayA = digest({
      ids: firstIds,
      filtered: filteredIds,
      window: windowed.result.map((row) => row.candidateId),
      export: exported.result,
    });
    const replayB = digest({
      ids: fixture.map((row) => row.candidateId),
      filtered: filterCandidates(fixture, {
        query: "",
        risk: "high",
        decision: "all",
        topOnly: false,
        topN: false,
      }).map((row) => row.candidateId),
      window: windowCandidates(
        filterCandidates(fixture, {
          query: "",
          risk: "high",
          decision: "all",
          topOnly: false,
          topN: false,
        }),
        0,
        WINDOW_SIZE,
      ).map((row) => row.candidateId),
      export: normalizeExport(fixture),
    });
    assert.equal(replayA, replayB);

    const topN = filterCandidates(fixture, {
      query: "",
      risk: "all",
      decision: "all",
      topOnly: false,
      topN: true,
    });
    assert.equal(topN.length, STABLE_TOP_N);
    assert.deepEqual(
      topN.map((row) => row.candidateId),
      firstIds.slice(0, STABLE_TOP_N),
    );

    timings[size] = {
      normalize_ms: Number(normalized.elapsedMs.toFixed(3)),
      filter_ms: Number(filtered.elapsedMs.toFixed(3)),
      window_ms: Number(windowed.elapsedMs.toFixed(3)),
      render_model_ms: Number(render.elapsedMs.toFixed(3)),
      export_ms: Number(exported.elapsedMs.toFixed(3)),
      replay_sha256: replayA,
    };
  }

  process.stdout.write(`${JSON.stringify({ cockpit_perf_benchmark: timings }, null, 2)}\n`);

  const filterSource = await readFile(new URL("lib/filterCandidates.ts", featureRoot), "utf8");
  const windowSource = await readFile(new URL("lib/windowCandidates.ts", featureRoot), "utf8");
  assert.doesNotMatch(filterSource, /\.sort\(/);
  assert.doesNotMatch(windowSource, /\.sort\(/);
});
