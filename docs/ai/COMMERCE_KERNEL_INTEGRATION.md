# Commerce integration over the #248 kernel

PR #248 owns `backend.economics.kernel`. PR #250 consumes that kernel
through `evaluation.commerce.kernel_integration`. This file is not a second
economics authority.

## Authority

| Concern | Owner |
| --- | --- |
| Money, FX, evidence, unit/service formulas | `backend.economics.kernel` (#248) |
| Supplier-offer mapping, service mapping, client projection, replay fingerprint | `evaluation.commerce.kernel_integration` (#250) |
| Business-model dispatch | `evaluation.commerce.business_model_economics` (#250) |
| Dry-run lifecycle | `evaluation.commerce.dry_run_lifecycle` (#250) |

Kernel implementation files on this branch are byte-identical to #248
(`backend/economics/kernel.py` SHA `4baba4be5bcddeab71d841d0d8f26f84a7c8bef3`).
Do not edit them here. Merger merges #248 first.

## Contracts

- `economics_payload` — canonical kernel dict plus `kernel_authority`
- `supplier_offer_to_economics` — supplier price/cost/lane → `calculate_unit_economics`
- `service_package_to_economics` — service fee + intake → `calculate_service_economics`
- `compatibility_unit_economics` — float-shaped caller adapter
- `client_safe_projection` — strips prompts/formulas/heuristics/credentials
- `replay_fingerprint` — sha256 over canonical JSON

USD/MXN/CAD never mix without explicit FX metadata. Unknown costs stay in
`missing_inputs`; placeholders are labeled assumed, never observed zero.

## Public patterns adapted (concepts only)

| Source | Version | License | Pattern | Decision |
| --- | --- | --- | --- | --- |
| Medusa (`medusajs/medusa`, npm `@medusajs/medusa` 2.21.0) | MIT (non-enterprise) | Module boundaries: money calc stays in one service | Reimplement as kernel consumption, do not vendor Medusa |
| Saleor (`saleor/saleor` 3.23.33, `720649d`) | BSD-3-Clause | Typed checkout money + currency code on every line | Map to kernel `Money.currency` |
| WooCommerce REST order/refund resource shape | GPL-3.0 (docs/API concepts only) | Explicit line items and refund reserves | Reserve fields already on kernel assumptions |
| Spree / Sylius order adjustment model | BSD-3 / MIT | Adjustments are additive, never silent FX | CurrencyMismatchError |
| OpenLineage 1.53.0 | Apache-2.0 | Run/job facets as evidence refs | `EvidenceRef` + replay fingerprint |
| Great Expectations | Apache-2.0 | Missing ≠ zero | `missing_inputs` |

No framework installed. No second event spine.
