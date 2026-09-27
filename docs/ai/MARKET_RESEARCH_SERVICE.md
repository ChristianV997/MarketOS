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
  -> services.market_research_evidence.report.build_evidence_integrity_report
       (candidate/workspace identity, source provenance, freshness, missing
        fields, and deterministic cross-pillar conflicts; no ranking)
  -> evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis
       (sole fusion/ranking authority: marketplace + supplier + consumer
        pillars, alias-collision detection via alias_notes, recommendation
        and decision code)
  -> evaluation.trustos.client_workspace_isolation.check_workspace_leakage
       (client-safe projection check; no raw report export)
  -> services.reporting.render.render_markdown_report / json_safe
       (shared markdown renderer and float-safety helper, reused verbatim)
```

No file under `evaluation/companyos/`, `backend/economics/kernel.py`, or any
unmerged consumer-attention / supplier-feasibility authority extension is
imported. Those live only in open, unmerged pull requests as of this work
(#295, #302) and are treated as unavailable rather than fabricated.

The integrated contract requires `workspace_id` for an identity-bound report.
Source reports may carry an optional workspace claim, but a mismatched claim
is rejected before either canonical authority runs. A request without a
workspace remains available only as a legacy composition result and is marked
`blocked_identity_unavailable` for client-safe export.
Source reports that claim a workspace while the request is unbound are
rejected rather than silently binding the result to unverified input. Candidate
identifiers are validated even for unbound requests.

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
- `conflict` — surfaced separately via `source_conflicts`; the existing
  `opportunity_synthesis.alias_notes` remain pass-through for source-collision
  context, while the joined
  evidence authority adds field-level `conflict_findings` across pillars.
  Findings are reported, never averaged or resolved.

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
- The integrated result exposes `observation_source_identity`, `freshness`,
  `source_provenance`, `missing_data`, `evidence_class`, and deterministic
  `next_research_actions` without copying raw provider payloads.
- TrustOS checks a bounded `client_safe_projection`. Its status is
  `ready_for_trustos_review` only when workspace identity is bound and no
  leakage finding is present; it is not authentication, authorization, or
  launch approval.
- Report input is bounded by node count, nesting depth, string size, and total
  serialized output size. Non-finite numeric values, unsafe provider/raw
  payload markers, non-string mapping keys, and duplicate JSON manifest keys
  fail closed before canonical synthesis or evidence reporting.
- Every candidate row carries a safe, bounded candidate ID and duplicate IDs
  fail closed before synthesis. A product-validation matrix row is supplied
  only when the report or a nested ranking row binds the requested candidate.
  Aggregate open questions and risk flags are copied only when that report
  binds exactly the requested candidate, so a multi-candidate aggregate
  cannot cross.
- Candidate-scoped synthesis is performed after the requested candidate is
  selected. A template or another candidate cannot supply the requested
  candidate's headline, score, plan, price, or action. Alias notes are kept
  only when they name the requested candidate; notes about other rows do not
  enter that candidate's source conflicts. When the synthesis authority has
  no row for the requested candidate, its empty-input fallback score of `0.0`
  is reported as `"missing"`, which stays distinct from an explicit zero on
  a matched candidate. A supplied pillar that does not contain the requested
  candidate is reported as `missing` with a candidate-mismatch limitation.
- Aggregate product-validation open questions and risk flags are copied only
  when every bound identity on that report is exactly the requested
  candidate. A multi-candidate aggregate cannot cross onto the requested
  candidate. An explicit numeric zero, including `pages_observed: 0`, is
  preserved and is not replaced by a fallback field.

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
The integrated fields are part of the same public result rather than a second
report type: `workspace_id`, observation/source identities, freshness rows,
field-level conflict findings, evidence class, source provenance, missing
data, client-safe export status/projection, evidence-integrity fingerprint,
and next research actions. Missing values remain explicit; an explicit
numeric zero remains a supplied observation.

`render_market_research_markdown` renders the same data through the shared
`services.reporting.render.render_markdown_report` helper. The result carries
`dry_run=True`, `read_only=True`, `network_calls=False`, `mutated=False` —
this service performs no I/O beyond composing already-supplied report dicts.

## Operator entry point

`scripts/market_research_report.py --manifest <manifest.json> [--markdown] [--output PATH]`
is the documented, offline CLI entry point for this service, following the
same manifest-driven convention as `scripts/research_to_decision.py`. The
manifest supplies `candidate_id` plus each pillar report either inline or
as a `*_report_path` relative to the manifest's own directory (rejected if
it would escape that directory). It performs no I/O beyond reading the
manifest and any referenced report files, and writes output only when
`--output` is given. `tests/services/test_market_research/test_operator_entrypoint.py`
exercises it end to end, including a real subprocess invocation compared
against the in-process call. The loader rejects oversized manifests, duplicate
keys, path escapes, null workspace identities, malformed report shapes, and
output-file I/O failures as bounded structured rejections rather than
tracebacks.

## Status

Implemented and unit-tested (119 focused tests across the market-research and
market-research-evidence suites) against synthetic fixtures, including
dedicated conflict (`tests/fixtures/market_research/conflict.json`) and
stale/future (`tests/fixtures/market_research/stale_and_future.json`)
fixtures, plus a TrustOS-boundary test proving `check_workspace_leakage`
blocks client-safe export when free text the local input filter allows
(for example a query containing "prompt") still reaches the projection.
Formula-shaped, HTML, credential, and provider-payload values are rejected
before synthesis. Not integration-tested against any live marketplace,
supplier, or consumer-attention provider, and not live-validated — all
evidence in this service's test suite is fixture-supplied.
