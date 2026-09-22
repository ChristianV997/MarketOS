# Market Research Evidence Integrity

`services.market_research_evidence.build_evidence_integrity_report` is a
disjoint, additive audit layer that hardens the evidence-quality contract
underneath market-research reporting: typed provenance, freshness
classification, deterministic cross-source conflict detection, and explicit
missing/unknown states. It creates no second ranker, scorer, economics
kernel, provider, scraper, or network call, and it never resolves a
conflict — only reports it.

This is disjoint from `services.market_research`
(the product-agnostic report service, [PR #307](https://github.com/ChristianV997/MarketOS/pull/307),
open and unmerged at the time this was written). Nothing here depends on
that package's files; both can compose the same upstream authorities
independently, and #307's report can adopt this module later without
either side needing to change.

## The known concern this addresses

`evaluation.commerce.opportunity_synthesis`'s `alias_notes`
(SYN-ALIAS-NO-COLLAPSE) only fires when two **candidate rows** share an
explicit `source_family` tag and the same `query` text. It:

- never compares the same `candidate_id` as reported by two *different*
  pillars (e.g. a supplier's shipping quote vs. a public-market
  competitor's observed shipping cost for the same product);
- produces zero notes whenever `source_family` is simply absent from the
  evidence — which understates disagreement rather than proving its
  absence.

So a market-research report whose only conflict signal is a pass-through of
`alias_notes` can report "no conflicts" on evidence that actually
disagrees. `tests/services/test_market_research_evidence/test_report.py::test_this_conflict_is_not_the_alias_collapse_mechanism`
demonstrates this directly: a fixture with a single, unaliased
`candidate_id` per pillar (so `alias_notes` is empty) still surfaces two
real field-level conflicts (`price`, `shipping_cost`) via the new
deterministic detector.

## Call graph

```
services.market_research_evidence.report.build_evidence_integrity_report
  -> evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis
       (existing fusion authority; only its alias_notes are read, as a
        separately labeled pass-through — never recomputed)
  -> services.market_research_evidence.identity
       (typed SourceIdentity / ObservationIdentity, candidate+workspace
        binding validation)
  -> services.market_research_evidence.freshness.classify_freshness
       (supplied / stale / future / unknown / missing, 180-day window)
  -> services.market_research_evidence.conflict.detect_field_conflicts
       (new: deterministic, field-level, cross-source diff — a data-
        quality audit, not a ranker)
  -> evaluation.trustos.client_workspace_isolation.check_workspace_leakage
       (existing TrustOS client-safety boundary, reused as-is to prove the
        report payload is free of internal-only or secret-shaped fields
        before it is called client-export-safe)
  -> services.reporting.render.render_markdown_report / json_safe
       (shared renderer, reused as-is)
```

## Typed provenance and identity

- `SourceIdentity(source_family, source_ref)` — who produced one
  observation (a pillar plus its own reference, e.g. a supplier name or a
  competitor's `source_domain`), with a deterministic SHA-256 fingerprint.
- `ObservationIdentity(candidate_id, workspace_id, field)` — what fact is
  being observed; the join key conflict detection groups on.
- `validate_binding(candidate_id, workspace_id)` rejects any candidate or
  workspace id that isn't a bounded, safe identifier
  (`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`), so a report can never be built
  against an unbounded or injectable identity string.

## Freshness

`classify_freshness(observed_at, as_of, freshness_days=180)` returns one of
`supplied | stale | future | unknown | missing`. `missing` is for an absent
`observed_at`; `unknown` is for an `observed_at` that was supplied but
isn't a real calendar date — these are kept distinct so a report can never
claim freshness it didn't actually evaluate.

## Deterministic conflict detection

`detect_field_conflicts` groups a candidate's field observations by field
name (in sorted, stable order) and flags any field where two or more
independently sourced numeric values disagree beyond a fixed tolerance. It
is intentionally cross-source: `shipping_cost` and `price` are left
unprefixed so a supplier's own shipping quote and a public-market
competitor's observed shipping cost for the same candidate can be compared
directly, which is exactly the scenario `alias_notes` cannot see. Pillar-
specific score fields (e.g. `marketplace.overall_marketplace_opportunity`)
are prefixed by pillar, since they are not comparable units across
pillars. The function never averages, weights, or resolves a conflict —
it only reports it, with every contributing observation and its source.

## Missing-vs-zero and explicit unknown states

Every expected field that was never supplied, or whose candidate could not
be matched in a supplied pillar report, is recorded in `missing_fields` by
name (e.g. `supplier.shipping_cost`, `marketplace.candidate_not_matched`).
No field observation's `value` is ever coerced to `0`; an absent numeric
value is either omitted entirely (report/candidate missing) or recorded
as the literal string `"missing"`.

## Negative controls

`NegativeControls` is a fixed, always-`True` record —
`evidence_is_not_supplier_proof`, `evidence_is_not_legal_clearance`,
`evidence_is_not_promotion_approval`, `evidence_is_not_a_launch_approval` —
paired with the same four assurances in `limitations`. A dedicated test
scans both the JSON and Markdown output for the corresponding *affirmative*
claims (`"is supplier proof"`, `"approved for promotion"`, `"launch
authorized"`, `"is compliant"`, `"is certified"`, etc.) and asserts none of
them ever appear.

Note: the field name `evidence_is_not_launch_authorization` was rejected
during development — `check_workspace_leakage` treats the bare substring
`authorization` in any dict key as leakage-shaped regardless of a `not_`
prefix (it does not parse negation), so the field is named
`evidence_is_not_a_launch_approval` instead. This is the TrustOS boundary
doing its job: it is deliberately conservative about key names, not
content-aware, so satisfying it sometimes means renaming rather than
arguing with it.

## Redaction and client-safety boundary

Before a report is finalized, its full JSON-safe payload is passed through
`evaluation.trustos.client_workspace_isolation.check_workspace_leakage`
(the existing TrustOS client-export boundary, unmodified). Any finding is
recorded verbatim in `leakage_findings`, and `client_export_safe` is `False`
whenever any finding exists — this module never silently strips or hides a
flagged field, it surfaces the boundary's own verdict.

## Fingerprints

`fingerprint` is a SHA-256 over the sorted-JSON payload with `generated_at`,
`fingerprint`, `leakage_findings`, and `client_export_safe` excluded, so it
is stable for identical evidence and independent of wall-clock time or of
the leakage check's own (deterministic, but separately verifiable) output.

## Status

Implemented and unit-tested (39 tests,
`tests/services/test_market_research_evidence/test_report.py`) against
synthetic fixtures, including a dedicated cross-source logistics-conflict
fixture (`tests/fixtures/market_research_evidence/logistics_conflict.json`)
and a stale/future/unknown-freshness fixture
(`tests/fixtures/market_research_evidence/stale_and_future.json`). Not
integration-tested against any live marketplace, supplier, or public-market
provider, and not live-validated — all evidence in this test suite is
fixture-supplied.
