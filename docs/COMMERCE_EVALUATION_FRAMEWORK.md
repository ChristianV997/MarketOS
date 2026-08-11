# Commerce Intelligence Evaluation Framework

The Commerce Intelligence Evaluation Framework is the measurement layer for
MarketOS Phase 1. It evaluates the evidence produced by the existing Supplier
Evidence, Competition Intelligence, Opportunity Scoring, Research Portfolio,
and Margin Intelligence engines. It does not add another scorer, provider, or
decision path.

## Purpose and boundary

The framework answers questions such as:

- Did a new extraction method increase observed supplier-field coverage?
- Did competition pricing coverage or duplicate detection improve?
- Did opportunity confidence and ranking stability change?
- How much of a run is still assumption-based?
- Is the complete Commerce MVP run more reproducible and evidence-complete?

Reports are deterministic, read-only, and advisory. They do not promote a
candidate, change a feature flag, call a provider, publish an artifact, create
an order, or authorize spend. Evaluation events use the existing canonical
`Event` contract and may be written only when an operator explicitly requests
an output path.

## Architecture

```text
validation_report.json / events.jsonl / replay workspace
                    |
                    v
        evaluation.commerce.service
                    |
                    +--> pure engine metrics
                    +--> reproducibility and replay hashes
                    +--> optional Run A / Run B comparison
                    +--> canonical evaluation events
                    |
                    v
          CLI JSON/Markdown or GET-only API views
```

The loader accepts a validation artifact, canonical JSONL, replay JSONL, or a
directory containing `validation_report.json` and/or `events.jsonl`. It prefers
the named validation report and uses deterministic directory ordering. No
network request is made and no input is modified.

## Metrics

### Supplier Evidence

Supplier evaluation reports attempted and observed products, observed and
missing fields, field observation rate, provenance distribution, confidence
histograms, cache status/hit rate, robots-blocked warnings, network failures,
and extraction method counts. Extraction methods distinguish JS-rendered and
static/JSON-LD observations where the source artifact records that provenance.

### Competition Intelligence

Competition evaluation reports offer count, observed competitor pricing,
pricing coverage, market spread, mean/median, population variance, duplicate
count/ratio, and source distribution. A missing price is not treated as a
zero-price observation.

### Opportunity Scoring

Opportunity evaluation reports score and confidence distributions, high-
confidence (`>= 0.70`) and low-confidence (`< 0.40`) counts, and the observed
ranking. Ranking stability is computed when comparing two evaluated runs with
shared candidate identifiers.

### Research Portfolio

Research evaluation reports candidate and cluster counts, cluster-confidence
quality, duplicate groups, duplicate ratio, canonicalization rate, ranking
movement events, and portfolio bucket counts.

### Margin Intelligence

Margin evaluation reports observed margin fields and their provenance, pricing
and margin confidence, and explicit assumption count/percentage. Assumptions
remain assumptions; public evidence is not converted into realized profit,
ROAS, conversion, CAC, or supplier viability.

### Overall Commerce Run

Overall metrics combine supplier-field completeness and competition-pricing
coverage into evidence completeness, combine available confidence measures into
overall confidence, report assumption percentage, count measured engines, and
classify run quality as `high`, `medium`, `low`, or
`insufficient_evidence`. The classification is a measurement summary, not a
promotion decision.

## Comparing runs

Run comparison produces Run A, Run B, numeric deltas, improved/worsened/
unchanged metric paths, and ranking stability. Positive deltas are treated as
improvements except `overall.assumption_percentage`, where lower is better.
Metrics present in only one run are reported with a `null` delta rather than
invented baselines. This intentionally conservative comparison can show that
an extraction method changed coverage without claiming that it improved sales.

Example:

```powershell
python scripts/evaluate_commerce_run.py `
  --run-a artifacts/phase1-live-validation/before `
  --run-b artifacts/phase1-live-validation/after `
  --json `
  --output artifacts/evaluation_report.json
```

## CLI

Evaluate a validation artifact, event stream, replay, or workspace:

```powershell
python scripts/evaluate_commerce_run.py --artifact artifacts/phase1-live-validation/run --json
python scripts/evaluate_commerce_run.py --jsonl artifacts/commerce-mvp-events.jsonl --markdown
python scripts/evaluate_commerce_run.py --replay artifacts/commerce-mvp-events.jsonl --json
python scripts/evaluate_commerce_run.py --workspace artifacts/phase1-live-validation/run --markdown
```

The command prints to stdout by default. `--output` is required to create a
report file. `--write-evaluation-events` is separately required to append
canonical `commerce_evaluation_started`, `commerce_engine_evaluated`, and
`commerce_evaluation_completed` events to a JSONL repository.

## Read-only API

When the existing FastAPI application is running and the server-side
`MARKETOS_EVENT_READ_JSONL_PATH` points beneath `artifacts/`:

```text
GET /api/evaluations
GET /api/evaluations/readiness
GET /api/evaluations/compare
```

The comparison view additionally requires server-configured baseline and
current paths beneath `artifacts/`. There are no POST, PUT, PATCH, or DELETE
evaluation routes. API path configuration is server-side; browser requests
cannot select arbitrary local files and no Supabase service-role credential is
exposed.

## Interpretation and limitations

Evaluation quality is bounded by the evidence supplied to the engines. A high
coverage score means more fields were observed, not that the observations are
true forever. A high confidence score means the engine expressed confidence
under its current evidence model, not that demand, conversion, margin, or
launch readiness was proven. `insufficient_evidence`, warnings, and blockers
must remain visible in operator workflows.

The framework currently does not provide statistical significance tests,
causal attribution, human-label agreement, online business KPIs, or distributed
experiment assignment. It also cannot validate a live page that was never
successfully fetched. Those are future extensions requiring separately approved
data and privacy contracts.

## Future extensions

Safe future work includes calibrated confidence against reviewed labels,
quality thresholds per source, richer replay-diff explanations, and a
dashboard read view for evaluation reports. Any future extension must preserve
canonical events, deterministic replay, no-authority metadata, and the
read-only boundary.
