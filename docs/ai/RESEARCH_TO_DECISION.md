# Offline Research-to-Decision Packet

`python scripts/research_to_decision.py --manifest <manifest.json> --json`
builds the existing `product-validation-report-v1` packet from bounded local
evidence. It is a manual-first adapter, not a second scorer, readiness report,
workflow, provider client, or commerce authority.

## Input contract

The manifest requires a timezone-aware `captured_at` value and a Mexico-first
`lane` with explicit origin country, ship-from country, warehouse, destination
country/state, postal-code assumption, currency, tax/duty/brokerage/shipping
models, return destination and payer, payment method, compliance requirements,
support language, marketplace eligibility, delivery promise, evidence state,
and confidence. An evaluation cannot silently fall back to a global margin.
Each evidence input is a relative `.json` or `.csv` path under the manifest
directory. Inputs may be supplier, marketplace, consumer-attention, or
summarized observation evidence. Structured `pdf_derived` and `form`
observations are accepted as sanitized local records only and must identify the
supplier SKU, destination country, lane currency, capture/expiry times, and
extraction method. `candidate_ids` can
select rows from a bounded shared fixture without changing the source evidence.

The loader caps manifests at 128 KiB, evidence files at 256 KiB, records at 100
per file, and input files at 24. It rejects HTML, raw/log-like fields, secret
patterns, path traversal, missing IDs, unsupported destinations/currencies,
duplicate identities, unsafe source URLs, and lane currency or destination
mismatches. Conflicting supplier offers remain visible as quarantined evidence
but are excluded from canonical supplier scoring. Supplier rows are normalized into
bounded `SupplierOffer` evidence with exact SKU, price validity, stock,
warehouse/destination, shipping method, P50/P95 delivery, tracking, blind-shipping and
packaging, return address and payer, warranty/RMA/refund SLA, support owner and
response SLA, dropshipping/marketplace permissions, sample state, terms/policy
evidence, backup supplier, approval lifecycle, freshness, source, and
confidence. Missing terms are preserved as `unknown` and quarantine the offer;
expired offers are quarantined rather than scored as current. An explicit
approval state is never promoted automatically. The tracked approval sequence
is `candidate -> contacted -> information_received -> quote_verified ->
terms_verified -> sample_ordered -> sample_passed -> direct_ship_tested ->
RMA_tested -> approved`, with `suspended` and `rejected` terminal holds. It
does not read credentials,
call providers, or fetch URLs. Reviewed URLs are metadata-only evidence and are
accepted without query strings or fragments; observation audits retain labels
and counts rather than raw URL content. Output is not written unless `--output`
is explicitly supplied.

Every supplier, marketplace, consumer-attention, and structured observation
record receives a stable `evidence:<sha256-prefix>` reference. Explicit
`source_reference` and `extraction_method` values are validated, while legacy
imports use the bounded input label and a manual-import method as deterministic
provenance defaults. References are hashed before output, so URLs and document
paths are not copied into the packet. Bounded warning lists remain attached to
the evidence record without accepting raw logs or HTML.

## Existing authorities

The adapter passes accepted rows through the existing authorities:

- `backend.adapters.research.supplier_feasibility` and
  `evaluation.commerce.supplier_feasibility`;
- `backend.adapters.research.marketplace_trends` and
  `evaluation.commerce.marketplace_trends`;
- `backend.adapters.research.consumer_attention` and
  `evaluation.commerce.consumer_attention`;
- `evaluation.commerce.benchmark_matrix`;
- `evaluation.commerce.opportunity_synthesis`;
- `evaluation.commerce.product_validation_report`.

The final packet records `market_lane`, supplier offers, candidate identity,
lifecycle, observed values, economics, assumptions, missing evidence,
confidence, hard gates, decision/next action, safety flags, input audit, and a
deterministic SHA-256 replay fingerprint in the existing report `appendix`.
Supplier, marketplace demand, consumer attention, competition, economics, and
compliance remain separate evidence sections. Manual or fixture evidence never
authorizes launch, spend, orders, or provider actions. A packet with incomplete
or quarantined evidence remains `hold_for_manual_review`.
Conflicting offers remain visible in the appendix with a `conflicting_offer`
issue and a blocked candidate risk state; they never become accepted supplier
evidence.
Candidate audits additionally expose evidence references, extraction methods,
freshness, conflicts, and a conservative `risk_state`. The appendix's
`client_safe_projection` is a stable, read-only projection for cockpit, export,
and replay consumers; it carries no launch, spend, provider, or order
authority. The `integration_contract` points those consumers back to this
existing authority and the existing `product-validation-report-v1` packet.

## Evidence-promotion lifecycle

Each candidate audit also carries a bounded `promotion_lifecycle` transition
ledger. It is an extension of the existing appendix, not a second packet or
readiness authority. Transitions use the states `discovered`, `normalized`,
`screened`, `evidence_incomplete`, `supplier_claimed`,
`supplier_documented`, `offer_conflicted`, `lane_verified`,
`sample_required`, `direct_ship_required`, `rma_required`,
`economics_ready`, `competition_ready`, `promotion_blocked`,
`launch_candidate`, `launch_authorized_false`, `manually_approved`, and
`live_validated` where compatible with available evidence. Every transition
contains its prior and next state, reason code, hashed evidence IDs, evidence
state, actor/source, captured timestamp, blocking conditions, candidate ID, and
a SHA-256 `replay_identity` over those fields.

The adapter emits `launch_authorized_false` for offline packets and never emits
`manually_approved` or `live_validated` from fixture, manual, assumed, or
simulated evidence. Conflicting offers stay visible but add a blocking
`offer_conflicted` transition and are excluded from canonical supplier
scoring. The client-safe projection exposes `decision_outcome` using the
existing operator outcomes `reject`, `hold_for_manual_review`,
`needs_evidence`, `deferred`, `candidate_only`, and `launch_candidate` without
granting merge, launch, spend, or provider authority.

## Evidence mode

This path is offline and read-only. A generated packet is a reproducible
operator handoff, not live supplier proof. Live supplier validation, public-page
retrieval, credentials, and external mutations remain separate approval-gated
capabilities.
