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
observations are accepted as sanitized local records only. `candidate_ids` can
select rows from a bounded shared fixture without changing the source evidence.

The loader caps manifests at 128 KiB, evidence files at 256 KiB, records at 100
per file, and input files at 24. It rejects HTML, raw/log-like fields, secret
patterns, path traversal, missing IDs, unsupported destinations/currencies,
duplicate identities, conflicting same-identity records, unsafe source URLs,
and lane currency or destination mismatches. Supplier rows are normalized into
bounded `SupplierOffer` evidence with exact SKU, price validity, stock,
warehouse/destination, P50/P95 delivery, tracking, blind-shipping and
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

## Evidence mode

This path is offline and read-only. A generated packet is a reproducible
operator handoff, not live supplier proof. Live supplier validation, public-page
retrieval, credentials, and external mutations remain separate approval-gated
capabilities.
