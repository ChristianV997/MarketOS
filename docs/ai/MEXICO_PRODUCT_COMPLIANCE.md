# Mexico product-compliance policy overlay

- lane: MEXICO-PRODUCT-COMPLIANCE-POLICY-V1
- access date: 2026-09-19
- not legal advice
- maps onto the canonical `promotion.compliance` gate
- does **not** add a GATE_ID, registry, scorer, or live lookup

## Contract for Claude / Grok Bot

| Field | Value |
| --- | --- |
| Gate | `evaluation.commerce.promotion.GATE_IDS` → `compliance` only |
| Packs | existing `privacy_legal_baseline` and `tax_accounting_readiness` |
| Evaluator | `evaluation.trustos.mexico_product_compliance.evaluate_mexico_product_compliance` |
| Satisfaction map | `decision.promotion_gate_satisfaction()` → `{"compliance": bool}` |
| Fail-closed | unlisted evidence, unknown bands, missing RFC/CFDI/pedimento/HS, stale citations, cancelled/mismatched CoH |
| Non-Mexico | `united_states` / `canada` / `unknown` → every requirement `not_assessed`; compliance false from this overlay |
| Non-radio hydro | IFT/NOM-208 `not_applicable`; other MX sale/import duties still apply |
| Dual-band / 4G | do **not** guess IFT-016 / IFT-017 / IFT-011; hold `compliance` |
| Evidence classes | `official_db` may satisfy; `supplier_claim` / `fixture` / `unknown` never satisfy launch |
| Already sold in MX | warning only; never auto-clears |
| Consumer | do **not** edit `product_validation_report.py`; it remains a consumer of `promotion.compliance` |

Statuses preserved: `needs_evidence` | `not_assessed` | `not_applicable`. `satisfied` is internal and only when official, fresh, model-matched evidence exists.

## Requirement families

| Family | Pack | Examples |
| --- | --- | --- |
| import_customs | tax_accounting_readiness | HS/TIGIE, pedimento, IMMEX if claimed |
| tax_invoicing | tax_accounting_readiness | RFC, CFDI 4.0, IVA |
| labeling_safety | privacy_legal_baseline | NOM-003-SCFI, NOM-024-SCFI, NOM-001-SEDE, LFPC/PROFECO, LICal |
| telecom_homologation | privacy_legal_baseline | LMTR 271-272, CoH, NOM-208/IFT-008 when 2.4 confirmed |
| sector_permits | privacy_legal_baseline | COFEPRIS, SEMARNAT, Ley General de Salud |

## Product families encoded

`hydroponics_non_radio`, `hydroponics_radio_iot`, `smart_pet_wifi_2_4`, `smart_pet_uncertain_band`, `telecom_wifi_2_4`, `telecom_dual_band`, `telecom_cellular_4g`, `unknown_family`.

No SKU is certified by family. Exact model + official evidence is required before `compliance` can be true.

## Source classifications (access 2026-09-19)

See `mexico_policy_sources()` for URLs, issuing authority, publication/effective dates, and `verified_legal_text` vs `official_observation` vs `unresolved_interpretation`.

Unresolved for a human/lawyer/customs broker:

1. Whether CRT has republished IFT 2021 homologation lineamientos unchanged.
2. IFT-016 vigencia 3 Nov 2025 (IFT archive table) vs 7 Feb 2025 + 270 days = 4 Nov 2025.
3. Whether a given nutrient/seed/pet-food SKU is COFEPRIS vs SADER/SENASICA.
4. Graphic Sello IFT start date.
5. Exact derechos / fees after CRT Pleno.
6. HS code for any real SKU.

## Safety

No live ehomologados scrape, no supplier contact, no credentials, no legal/tax conclusion, no second gate.
