# Offline Research-to-Decision Packet

`python scripts/research_to_decision.py --manifest <manifest.json> --json`
builds the existing `product-validation-report-v1` packet from bounded local
evidence. It is a manual-first adapter, not a second scorer, readiness report,
workflow, provider client, or commerce authority.

## Input contract

The manifest requires a timezone-aware `captured_at` value and a lane with
`origin`, `destination`, and one of the supported three-letter currencies. Each
evidence input is a relative `.json` or `.csv` path under the manifest directory.
Inputs may be supplier, marketplace, consumer-attention, or summarized
observation evidence. `candidate_ids` can select rows from a bounded shared
fixture without changing the source evidence.

The loader caps manifests at 128 KiB, evidence files at 256 KiB, records at 100
per file, and input files at 24. It rejects HTML, raw/log-like fields, secret
patterns, path traversal, missing IDs, unsupported destinations/currencies,
duplicate identities, conflicting same-identity records, unsafe source URLs,
and lane currency or destination mismatches. It does not read credentials, call
providers, or fetch URLs. Reviewed URLs are metadata-only evidence and are
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

The final packet records lane, lifecycle, economics, assumptions, missing
evidence, confidence, next action, input audit, safety flags, and a deterministic
SHA-256 replay fingerprint in the existing report `appendix`. Manual or fixture
evidence never authorizes launch, spend, orders, or provider actions. A packet
with incomplete evidence remains `hold_for_manual_review`.

## Evidence mode

This path is offline and read-only. A generated packet is a reproducible
operator handoff, not live supplier proof. Live supplier validation, public-page
retrieval, credentials, and external mutations remain separate approval-gated
capabilities.
