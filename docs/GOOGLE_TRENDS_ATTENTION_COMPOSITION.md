# Google Trends attention composition

Offline bridge from the official Google Trends relative-interest adapter to the
existing consumer-attention report builder.

Stacked on the adapter branch. It does not change that adapter, insight
synthesis, the query planner, or the brief-driven runner.

## What it preserves

Each fixture point stays on `source_series`:

- term, time resolution, and observation period
- geography only when the fixture point or series entry stated it
- language only as `language_metadata` when the fixture point or series entry stated it
- `relative_interest` exactly, including `null` (missing is not zero)
- status, freshness, provenance, method, and collected time

Request-level geography and language stay on `request_geography` and
`request_language_metadata`. They are not copied onto a point that omitted them.
Public Trends API pages do not confirm a language filter, so canonical
`language` stays empty. `language_filter_confirmed` is false.

## What it refuses

- Relative interest is not absolute volume, a website 0–100 score, sales, or purchase intent.
- It is not written to `keyword` or `search_growth_signal`.
- `available_for_scoring` and `score_represents_relative_interest` stay false.
- The canonical report may still contain a non-interest score from other empty attention fields. That number is not the Trends metric.
- Fixture, manual, and blocked-live output are never labeled live.
- A query plan is not evidence.
- `candidate_id_hint` and a candidate id that merely repeats the term are ignored. Only an explicit `term=candidate_id` link binds a row. Unbound rows use `unbound-search-interest`.

## Run

```powershell
python scripts/run_google_trends_attention_bridge.py --fixture tests/fixtures/google_trends_interest_adapter/trends_interest_valid.json --identity-link "desk fan=cand-desk-fan"
```

The command prints JSON and does not call the network.
