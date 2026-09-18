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

Kernel implementation files remaining on this branch are byte-identical to #248
(`backend/economics/kernel.py` SHA `4baba4be5bcddeab71d841d0d8f26f84a7c8bef3`).
Do not edit them here. Merger rebases onto #248 and drops the copies.

## Contracts

- `economics_payload` — canonical kernel dict plus `kernel_authority`
- `supplier_offer_to_economics` — supplier price/cost/lane → `calculate_unit_economics`
- `service_package_to_economics` — service fee + intake → `calculate_service_economics`
- `compatibility_unit_economics` — float-shaped caller adapter
- `client_safe_projection` — strips prompts/formulas/heuristics/credentials
- `replay_fingerprint` — sha256 over canonical JSON
- `missing_evidence` — explicit missing-input tuple; never silent zero
- `assert_offline` — blocks place_order / capture_payment / launch_ad language

USD/MXN/CAD never mix without explicit FX metadata. Unknown costs stay in
`missing_inputs`; placeholders are labeled assumed, never observed zero.
Fixture/manual/simulated evidence is not upgraded to observed/verified.

## Public patterns adapted (concepts only)

| Source | Version / commit | License | Pattern | Decision |
| --- | --- | --- | --- | --- |
| Medusa (`medusajs/medusa`) | develop LICENSE 2026-09 | MIT core; Enterprise Edition excluded | Money calc stays in one service | Reimplement as kernel consumption; do not vendor Medusa |
| Saleor (`saleor/saleor`) | 3.x line | BSD-3-Clause | Typed checkout money + currency on every line | Map to kernel `Money.currency` |
| WooCommerce REST order/refund resource shape | docs/API concepts | GPL-3.0 concepts only; no source copied | Explicit refund/reserve lines | Reserve fields already on kernel assumptions |
| Spree Commerce / Sylius | BSD-3 / MIT | Adjustments additive; no silent FX | `CurrencyMismatchError` |
| OpenLineage | 1.53.0 | Apache-2.0 | Run/job facets as evidence refs | `EvidenceRef` + replay fingerprint |
| Great Expectations | current public docs | Apache-2.0 | Missing is not zero | `missing_inputs` / `missing_evidence` |

No framework installed. No second event spine. No live provider/order/payment execution.

## #256 compatibility

PR #256 (`56810fc`) bases on old #250 SHA `f48dfb1842719ecbbc2b6db2d7a858cadcfe5d20`
and imports `DryRunLifecycleReport`, `run_dry_run_lifecycle`, `SCENARIO_BUILDERS`,
`Money`, `build_service_engagement`, and `evaluate_promotion`. Those public
signatures are unchanged. #256 was not edited. After #250 is rebased onto #248,
#256 must be rebased onto the new #250 HEAD before merge.
