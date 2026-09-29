# Mexico product-compliance policy overlay

- lane: MEXICO-PRODUCT-COMPLIANCE-POLICY-V1
- legal-source access date: 2026-09-19 (unchanged since; no cited rule has been re-verified after this date)
- consumer-architecture last updated: 2026-09-22 (offering_kind gating and the four report consumers documented below; no new legal source consulted for this update)
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
| Consumer | `evaluation.commerce.market_access_report` projects this evaluator's decision into every live recommendation surface (see "Consumer surfaces and offering_kind" below); it never recomputes law, never adds a second gate/registry, and never edits this evaluator's own files |

Statuses preserved: `needs_evidence` | `not_assessed` | `not_applicable`. `satisfied` is internal and only when official, fresh, model-matched evidence exists.

## Consumer surfaces and offering_kind (added, this document updated 2026-09-22)

MarketOS recommends goods, services, and hybrids, but this evaluator only ever modeled goods (customs/telecom/NOM requirements). `evaluation.commerce.market_access_report` reads an additive `offering_kind` from the candidate dict (`"goods"` / `"service"` / `"hybrid"` / `"unknown"`, defaulting to `"goods"` so every pre-existing goods-only caller is unaffected) and gates which of this evaluator's requirements are even applicable **before** calling it — it never asks this evaluator to reason about services, and it never invents a second evaluator for them:

| `offering_kind` | Customs / telecom / physical-NOM requirements (`mx_hs_classification`, `mx_pedimento`, `mx_immex`, `mx_telecom_homologation`, `mx_nom_208_radio`, `mx_nom_electrical_safety`, `mx_nom_labeling`) | Sector/consumer-labeling requirements this repo only models for goods today (`mx_lfpc_profeco`, `mx_infraestructura_calidad`, `mx_ley_general_salud`, `mx_cofepris_sector`, `mx_semarnat_sector`) | Fiscal duties (`mx_importer_rfc`, `mx_cfdi`, `mx_iva`) |
| --- | --- | --- | --- |
| `goods` (default) | evaluated normally by this evaluator | evaluated normally by this evaluator | evaluated normally |
| `service` | `not_applicable` (no physical good exists to classify/label/homologate) | `not_assessed` (no service-sector evaluator exists here — never falsely cleared, never falsely blocked) | still evaluated (jurisdiction-wide sale duties, not goods-specific) |
| `hybrid` | evaluated exactly as `goods` (nothing else to base it on) | evaluated exactly as `goods`, plus a warning that the service component is not covered | still evaluated |
| `unknown` (declared or unrecognized) | `not_assessed` | `not_assessed` | `not_assessed` |

A pure `service` offering can therefore never show `compliant` for Mexico — there is no canonical evaluator for Mexican service-sector licensing/health/environmental requirements yet, so those stay `not_assessed` rather than being silently cleared. This is a report-layer projection choice, not a change to this evaluator's own logic: `evaluate_mexico_product_compliance()` itself is never called with a "service" market or product family — it only ever sees `mexico`/`united_states`/`canada` and the existing `PRODUCT_FAMILIES` tuple, exactly as before.

Consumer surfaces receiving the identical projection (proven by cross-consumer contract tests, `tests/test_market_access_cross_consumer_contract.py` and `tests/test_market_access_offering_kind_cross_consumer.py`): `evaluation.commerce.product_validation_report.ProductValidationReport`, `evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis`, `evaluation.commerce.launch_draft_pack.build_launch_draft_pack`, `evaluation.commerce.site_draft_builder.build_site_draft_pack`.

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
7. Mexican **service-sector** licensing, health, and environmental requirements have no canonical evaluator in this repository yet. A declared `service` offering reports these as `not_assessed` (never silently cleared, never blocked by goods-only physical rules) -- a human must confirm no such requirement is missing from this system's model entirely before treating any real service offering's Mexico section as complete.
8. `hybrid` offerings only get their goods component assessed by this evaluator; the service component is flagged `not_assessed` via warning, never evaluated.

## Implementation note for the evaluator's owner (observed, not fixed here -- different lane)

`evaluate_mexico_product_compliance()`'s `_from_evidence()` and the module-level `NON_SATISFYING_EVIDENCE` constant both treat `"manual"` as a non-satisfying evidence-class value, but `MexicoProductCompliancePacket.__post_init__` validates every `*_evidence_class` field against `EVIDENCE_CLASSES = ("official_db", "supplier_claim", "fixture", "unknown")`, which does not include `"manual"` -- so a caller can never actually construct a packet with `evidence_class="manual"` (it raises `ValueError` first), making that branch and `NON_SATISFYING_EVIDENCE` unreachable dead code. This is a code-quality observation confirmed by reading the evaluator directly (not by a failing test — no caller anywhere in this repository passes `"manual"` as an evidence class, so nothing currently depends on the broken path). It does not affect any status this document or the consumer projection reports today. Flagged here rather than fixed, since `evaluation/trustos/mexico_product_compliance.py` is owned by a separate lane and this document's own scope is the consumer projection, not the evaluator's internals.

## Safety

No live ehomologados scrape, no supplier contact, no credentials, no legal/tax conclusion, no second gate.
