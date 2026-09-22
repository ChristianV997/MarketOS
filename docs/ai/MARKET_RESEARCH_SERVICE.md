# Market Research Service

`services.market_research.build_market_research_report` composes an offline,
consulting-ready market research report for one candidate offering. It is a
product-agnostic composition layer, not a second scorer, ranking engine, or
promotion gate. It creates no new evidence, no new fusion math, and no new
decision authority — every score, recommendation, and conflict note is
read straight from `evaluation.commerce.opportunity_synthesis`.

## Call graph

```
services.market_research.report.build_market_research_report
  -> evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis
       (sole fusion/ranking authority: marketplace + supplier + consumer
        pillars, alias-collision detection via alias_notes, recommendation
        and decision code)
  -> services.reporting.render.render_markdown_report / json_safe
       (shared markdown renderer and float-safety helper, reused verbatim)
```

No file under `evaluation/companyos/`, `backend/economics/kernel.py`, or any
unmerged consumer-attention / supplier-feasibility authority extension is
imported. Those live only in open, unmerged pull requests as of this work
(#295, #302) and are treated as unavailable rather than fabricated.

## Offering kinds

`offering_kind` is one of `goods`, `service`, `hybrid`, `unknown`
(`schemas.OFFERING_KINDS`). An unrecognized raw value fails closed to
`"unknown"` with a recorded limitation (`_recognized_offering_kind`), mirroring
`evaluation/commerce/market_access_report.py`'s `_recognized_offering_kind`
pattern. All four kinds flow through the same composition path; `service` and
`hybrid` offerings additionally receive a follow-up-module hint when supplier
or delivery evidence is absent, since neither is guaranteed to apply.

## Evidence classes

Each of the five input pillars (`marketplace`, `supplier`, `consumer_attention`,
`public_market_benchmark`, `product_validation`) gets one
`EvidenceMatrixRow` with a status from `schemas.EVIDENCE_STATUSES`:

- `supplied` — present and within the freshness window.
- `missing` — not supplied on the request at all.
- `stale` — `observed_at` predates `as_of` by more than
  `DEFAULT_FRESHNESS_DAYS` (180 days, the same window convention used by
  `evaluation.trustos.mexico_product_compliance`'s citation-freshness check).
- `future` — `observed_at` is after `as_of`.
- `conflict` — surfaced separately via `source_conflicts`, which is a direct
  pass-through of `opportunity_synthesis`'s existing `alias_notes` (the
  `_candidate_map` / `_identity_key` alias-collision detector); this service
  never recomputes conflict detection.

Pillars whose `evidence_mode` is in `FIXTURE_LIKE_EVIDENCE_MODES` (`fixture`,
`fixture_demo`, `manual_import`, `manual`) are flagged in the row's notes —
never silently treated as equivalent to a `LIVE_EVIDENCE_MODES` observation.

## Safety invariants (enforced, tested)

- Consumer attention is never presented as supplier proof.
- Marketplace/trend signal is never presented as launch authorization.
- A supplier's own claim is never presented as validation.
- Missing shipping cost or any other missing numeric evidence is reported as
  the literal string `"missing"`, never coerced to `0`
  (`_delivery_and_logistics_feasibility`, mirroring
  `supplier_feasibility.py`'s `shipping_cost_missing` flag).
- No second promotion gate or ranking engine is introduced; recommendation
  and decision code come from `opportunity_synthesis` only.

These four "never treat X as Y" invariants and the never-zero invariant are
each covered by a dedicated test in
`tests/services/test_market_research/test_report.py`, plus a negative-control
test that scans both the JSON and Markdown report bodies for
compliance/launch-authorization language that must never appear.

## Output

`build_market_research_report` returns a `MarketResearchResult` with an
executive summary (pass-through from the synthesis), the evidence matrix,
demand/competitor/marketplace/supplier/delivery/pricing sections, disjoint
`assumptions` vs. `observed_facts` lists, `source_conflicts`, a confidence
grade, `limitations`, `blockers`, `risks`, exactly one `next_action` string, a
non-empty bounded `validation_plan`, `follow_up_modules` naming only the
pillars that are actually missing, and a deterministic SHA-256 `fingerprint`
computed over the sorted-JSON payload with `generated_at` excluded (so
identical evidence always yields the same fingerprint).
`render_market_research_markdown` renders the same data through the shared
`services.reporting.render.render_markdown_report` helper. The result carries
`dry_run=True`, `read_only=True`, `network_calls=False`, `mutated=False` —
this service performs no I/O beyond composing already-supplied report dicts.

## Status

Implemented and unit-tested (33 tests,
`tests/services/test_market_research/test_report.py`) against synthetic
fixtures, including dedicated conflict (`tests/fixtures/market_research/conflict.json`)
and stale/future (`tests/fixtures/market_research/stale_and_future.json`)
fixtures. Not integration-tested against any live marketplace, supplier, or
consumer-attention provider, and not live-validated — all evidence in this
service's test suite is fixture-supplied.
