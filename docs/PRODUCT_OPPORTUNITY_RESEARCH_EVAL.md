# Product Opportunity Research Evaluation Harness

A deterministic, fixture-only harness that checks whether the existing
Product Opportunity Synthesis makes evidence-grounded, appropriately cautious
decisions. It is an evaluation, not a scorer. It adds no opportunity score,
changes no decision threshold, and calls no provider.

```text
packet (synthetic pillar reports + safety expectations + known gaps)
   |  read-only
   v
evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis
   |
   v
measure(): coverage, completeness, freshness, identity, currency, price, warnings
run_checks(): outcome versus expectation -> pass | known_gap | unexpected_fail
   |
   v
sorted JSON report (no timestamps, no paths, no raw values)
```

## Run it

```bash
python scripts/evaluate_product_opportunity_research.py
python scripts/evaluate_product_opportunity_research.py --scenario S04_cross_currency_join
python scripts/evaluate_product_opportunity_research.py --output <path>
```

- Exit `0`: no unexpected failures. Known gaps do not fail the run.
- Exit `2`: at least one expectation failed and no gap documents it.
- A full run takes about 20 seconds, almost all of it interpreter startup and
  imports. It reads the packet and the referenced fixtures, and it writes a file
  only when `--output` is given.

## Files

| File | Role |
|---|---|
| `scripts/evaluate_product_opportunity_research.py` | Harness: measurement, checks, report |
| `tests/fixtures/product_opportunity_eval/packet.json` | Scenarios, expectations, known gaps |
| `tests/system/test_product_opportunity_research_eval.py` | Harness tests |

The baseline scenario references the existing canonical trio under
`tests/fixtures/opportunity_synthesis/`. Nothing there is copied or edited.

## What it measures

Every value is computed from the packet inputs or the synthesis output. None is
a new score.

| Metric | Definition |
|---|---|
| `pillars_supplied` | Pillars with at least one candidate in the input |
| `effective_pillars` | Pillars with at least one evidence item whose consumer freshness is not wholly `unavailable` |
| `reported_coverage_matches_effective` | Synthesis `source_reports` count versus `effective_pillars` |
| `completeness` | Present required fields over required fields, across evidence items (harness-defined field lists) |
| `incomplete_items` | Evidence items with at least one required field missing |
| `freshness` | Per candidate and pillar: `fresh`, `stale`, `future_dated`, `unavailable`, or `unrepresented` |
| `identity_conflicts` | Candidates in two or more pillars whose normalized `query` differs |
| `currency_unreconciled` | Candidates whose marketplace and supplier items carry more than one currency |
| `currency_unstated_items` | Marketplace or supplier items with no currency field (informational) |
| `price_conflicts` | Candidates whose supplier `target_sell_price` lies outside the marketplace observed price band |
| `pillar_warnings` | `warnings` strings on pillar reports and candidates, and whether each reaches the synthesis output |

"Caution" means a string the synthesis emits in risk lists, blockers, threshold
assumptions, or alias notes. A caution counts only when it equals one of a fixed
set of exact codes for its category; matching is never by substring. The
`band` dictionary is excluded, because its `currency` key is a label, not a
caution. The synthesis emits no currency, identity, freshness, or price codes
today, so those checks are known gaps. The economics-missing codes count as
incomplete-evidence cautions only when a supplier pillar is present, because
the synthesis emits them whenever the supplier is absent.

## Expectations

Each scenario declares what a cautious decision must satisfy. The expectations
are safety policy written before the run. They are not canonical thresholds.

- `must_not_advance`: the overall recommendation must not be `advance_to_launch_draft`.
- `advance_must_be_draft_only`: any advance must carry the next action `prepare_launch_draft_for_human_review`.
- `max_grade`: the confidence grade must not exceed a ceiling.
- `required_blockers`, `assumptions_must_include`: named cautions must appear.
- `*_flagged`: when the harness measures a currency, identity, freshness, price, or incomplete-evidence problem, the output must carry a caution for it.
- `pillar_warnings_surfaced`: input warnings must appear in the output.
- `retained_candidates`, `min_alias_notes`, `expected_coverage`: structural checks.
- `non_authorization`: always checked. Outputs must be read-only, network-free, and non-mutating, and the next action must be a non-executing code. The `read_only`, `network_calls`, and `mutated` values are constants the synthesis reports about itself, so they are weak evidence on their own. The real mutation guard is an input snapshot, taken before measurement and compared again after the synthesis runs. A test forces a mutating synthesis and expects the run to fail.

A check that passes, or does not apply, is not reported as a gap. A failing
check is reported as a known gap only when the packet names that exact scenario
and check, with a reason. Any other failure is unexpected and fails the run.

## Baseline and final results

Baseline is the canonical trio alone, before any new scenario was added.

| Measure | Baseline (1 scenario) |
|---|---|
| Pillars supplied (mean) | 3.0 |
| Completeness (mean) | 1.0 |
| Freshness | `unrepresented` on all 6 candidate-pillar pairs |
| Identity, currency, price, incomplete, warnings | 0 |
| Unexpected failures | 0 |

Final, with 12 scenarios:

| Measure | Value |
|---|---|
| Checks applicable | 85 (65 not applicable) |
| Pass | 72 |
| Known gap | 13 |
| Unexpected failures | 0 |
| Pillars supplied (mean) | 2.83 |
| Completeness (mean) | 0.977 |
| Freshness | fresh 9, stale 1, unavailable 1, unrepresented 27 |
| Identity conflicts, currency unreconciled, price conflicts | 1 each |
| Incomplete evidence items | 3 |
| Pillar warnings: input / surfaced | 1 / 0 |
| False-ready scenarios (must not advance, but advanced) | S04, S05, S06, S07, S09 |
| False-confidence scenarios (grade above ceiling) | none |

An independent read-only review of the first commit returned request-changes.
Its findings were checked against the code and corrected before the final run:
the mutation guard compared the synthesis input against a copy it never touched;
caution matching was by substring and could be satisfied by unrelated codes; an
unknown `--scenario` id ran zero scenarios and exited 0; unknown expectation keys
and gap check names were not rejected; and a source with partly unavailable
observations was classed as fresh. The corrected run produces the same numbers
as before, and 30 tests cover the corrections.

The sequence was: the baseline run; then the new scenarios with empty known
gaps, which produced 13 unexpected failures; then the known gaps, each recorded
with its reason and synthesis line reference; then the final run with 0
unexpected. The first pass also found a harness bug: an incomplete-evidence token
matched an ordinary assumption, so one check passed vacuously. The token was
narrowed and a regression test was added. No expectation was changed.

## The 8 known gaps (findings for the synthesis owner)

| Gap | Scenario | What the synthesis does |
|---|---|---|
| `GAP-CURRENCY-UNRECONCILED` | S04 | Price band labelled USD unconditionally, and margin computed across mismatched currencies |
| `GAP-STALE-ATTENTION-UNGATED` | S05 | `freshness_statuses` reported in the matrix but never gates a recommendation or grade |
| `GAP-UNAVAILABLE-CONSUMER-UNFLAGGED` | S08 | An unavailable consumer source produces no caution |
| `GAP-UNAVAILABLE-COUNTED-AS-SUPPLIED` | S08 | A present report with no evidence items counts as a supplied pillar |
| `GAP-PRICE-CONFLICT-UNFLAGGED` | S06 | Supplier target price outside the observed marketplace band is not compared |
| `GAP-INCOMPLETE-EVIDENCE-PROCEEDS` | S07 | Missing price, delivery window, or platform does not block advance |
| `GAP-IDENTITY-JOIN-UNFLAGGED` | S09 | Pillars are joined on `candidate_id` alone; query mismatch is silent |
| `GAP-PILLAR-WARNINGS-DROPPED` | S10 | Pillar warnings are never read |

These are reported, not fixed. Fixing them means changing the synthesis, which
is owned by its own lane.

## What it cannot establish

- **Real-world correctness.** The packets are hand-written synthetic fixtures.
  A clean run shows the synthesis behaves as the packet's expectations describe,
  not that any product, price, or supplier is real.
- **Live validation.** Fixture success is not live validation and must not be
  cited as such. Every packet pillar is labelled `fixture` or `fixture_demo`, and
  a test enforces that.
- **Policy correctness.** The expectations are a safety position. A different
  policy could reasonably disagree with `must_not_advance` for a given scenario.
  The expectations are explicit so that a disagreement can be argued in review.
- **Source truth or freshness truth.** Freshness is only what a packet labels.
  Marketplace and supplier pillars carry no observation timestamp, so their
  freshness is `unrepresented` by construction.
- **The pillar modules themselves.** The harness exercises the synthesis, not the
  marketplace, supplier, or consumer scorers.
- **Thresholds or scores.** Nothing here tunes a threshold or validates a score.
  Completeness field lists and caution vocabularies are harness-level choices and
  are listed above; changing them changes the measurements.
- **Ownership or PR state.** It does not check open PRs, worktrees, or who owns a
  path. That is checked by hand before a lane starts.

## Scope and isolation

- Benchmark code lives under `scripts/`, outside production roots. Architecture
  boundaries require benchmarks never to be imported by production code.
- No credentials, provider calls, customer data, persistence, or external actions.
  A test forbids network, subprocess, and credential access in the harness source.
- Unmerged work is not used. The harness reads only refreshed `main`.
- Known overlaps, not touched here: PR #478 (titled "fail-closed cross-source
  product identity resolution") and PR #440 (titled "compare evidence currencies
  explicitly") may relate to `GAP-IDENTITY-JOIN-UNFLAGGED` and
  `GAP-CURRENCY-UNRECONCILED`. Their code was not read for this harness, and
  neither is merged. PR #465 owns benchmark API routes. All three are owned elsewhere.

## Rollback

Revert the PR, or delete the four added files: the harness, the packet, the test,
and this document. Nothing imports them.
