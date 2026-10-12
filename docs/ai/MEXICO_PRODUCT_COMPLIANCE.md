# Mexico product-compliance policy overlay

- lane: MEXICO-PRODUCT-COMPLIANCE-EVIDENCE-TO-READINESS
- legal-source access date: 2026-10-11 (lmtr-index, lfpc-index, crt re-checked this session; other cited rows carry prior publication/effective facts and are not newly certified)
- consumer-architecture last updated: 2026-09-22
- evidence-gap readiness surface added: 2026-10-11
- market-access operator action wired to evidence brief: 2026-10-12
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
| Launch-review readiness | `decision.launch_review_ready` tracks the same boolean; `decision.evidence_gaps` / `launch_review_evidence_brief()` explain open gaps |
| Fail-closed | unlisted evidence, unknown bands, missing RFC/CFDI/pedimento/HS, stale citations, cancelled/mismatched/conflicting CoH |
| Non-Mexico | `united_states` / `canada` / `unknown` → every requirement `not_assessed`; compliance false from this overlay |
| Non-radio hydro | IFT/NOM-208 `not_applicable`; other MX sale/import duties still apply |
| Dual-band / 4G | do **not** guess IFT-016 / IFT-017 / IFT-011; hold `compliance` |
| Evidence classes | `official_db` may satisfy when fresh/model-matched; `supplier_claim` / `fixture` / `unknown` / `manual` / `conflicting` never satisfy launch |
| Already sold in MX | warning only; never auto-clears |
| Consumer | `evaluation.commerce.market_access_report` projects this evaluator's decision into live recommendation surfaces; it never recomputes law |

Statuses preserved: `needs_evidence` | `not_assessed` | `not_applicable`. `satisfied` is internal and only when official, fresh, model-matched evidence exists.

## Evidence gaps before human launch review

`MexicoComplianceDecision.evidence_gaps` lists each open `needs_evidence` requirement with:

| Field | Meaning |
| --- | --- |
| `family` | One of `import_customs`, `tax_invoicing`, `labeling_safety`, `telecom_homologation`, `sector_permits` |
| `evidence_class` | Recorded class (`unknown`, `supplier_claim`, `fixture`, `manual`, `conflicting`, or stale `official_db`) |
| `reason_code` | `missing_official_evidence` / `non_official_evidence` / `stale_citation` / `conflicting_evidence` / `not_assessed_market` / `missing_exact_sku_model` |
| `needed_evidence` | Operator-facing description of what official evidence is still required |
| `satisfies_launch` | Always `false` for gap rows |

`launch_review_evidence_brief()` turns those rows into a single operator-facing paragraph. It never states that supplier/fixture/unknown/manual/conflicting/stale evidence clears `promotion.compliance`. Cleared packets still remind that lawyer/customs-broker/accountant review is required (not legal advice).

Cancelled or model-mismatched CoH rows that were recorded as `official_db` are projected as `conflicting` gaps so they cannot be mistaken for satisfying official evidence.

### Operator distinction on market-access surfaces

`evaluation.commerce.market_access_report` sets each Mexico jurisdiction's `next_human_action` to that same brief. Operators should read it as:

| Signal | Meaning |
| --- | --- |
| `promotion_gate.satisfied: false` + brief listing gaps | Official evidence is still missing or non-satisfying; do not treat as launch approval |
| `promotion_gate.satisfied: true` + brief human-review reminder | Recorded official evidence cleared the **metadata** `promotion.compliance` gate only; lawyer/customs-broker/accountant review is still required |
| US/CA `not_assessed` next action | Those markets are outside this evaluator; absence of a Mexico brief is not approval |

A missing or generic action string must never be interpreted as clearance. The consumer still never recomputes law and never creates a second compliance scorer.

## Consumer surfaces and offering_kind (added, this document updated 2026-09-22)

MarketOS recommends goods, services, and hybrids, but this evaluator only ever modeled goods (customs/telecom/NOM requirements). `evaluation.commerce.market_access_report` reads an additive `offering_kind` from the candidate dict (`"goods"` / `"service"` / `"hybrid"` / `"unknown"`, defaulting to `"goods"` so every pre-existing goods-only caller is unaffected) and gates which of this evaluator's requirements are even applicable **before** calling it — it never asks this evaluator to reason about services, and it never invents a second evaluator for them:

| `offering_kind` | Customs / telecom / physical-NOM requirements | Sector/consumer-labeling requirements | Fiscal duties |
| --- | --- | --- | --- |
| `goods` (default) | evaluated normally | evaluated normally | evaluated normally |
| `service` | `not_applicable` | `not_assessed` | still evaluated |
| `hybrid` | as `goods` | as `goods` + service-component warning | still evaluated |
| `unknown` | `not_assessed` | `not_assessed` | `not_assessed` |

Consumer surfaces receiving the identical projection: `ProductValidationReport`, `build_product_opportunity_synthesis`, `build_launch_draft_pack`, `build_site_draft_pack`.

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

## Source classifications (access 2026-10-11)

See `mexico_policy_sources()` for URLs, issuing authority, publication/effective dates, and `verified_legal_text` vs `official_observation` vs `unresolved_interpretation`.

Re-checked this session against primary pages:

1. LMTR Cámara index — DOF 16-07-2025, sin reforma (`https://www.diputados.gob.mx/LeyesBiblio/ref/lmtr.htm`).
2. LFPC Cámara index — última reforma DOF 12-12-2025; montos acuerdo DOF 23-12-2025 (`https://www.diputados.gob.mx/LeyesBiblio/ref/lfpc.htm`).
3. CRT agency page live (`https://www.gob.mx/crt`).

Unresolved for a human/lawyer/customs broker:

1. Whether CRT has republished IFT 2021 homologation lineamientos unchanged.
2. IFT-016 vigencia table date vs arithmetic 270-day calculation.
3. Whether a given nutrient/seed/pet-food SKU is COFEPRIS vs SADER/SENASICA.
4. Graphic Sello IFT start date.
5. Exact derechos / fees after CRT Pleno.
6. HS code for any real SKU.
7. Mexican **service-sector** licensing has no canonical evaluator here yet.
8. `hybrid` offerings only get their goods component assessed by this evaluator.

## OSS / prior-art adoption

No third-party compliance library, legal database client, or scraper was added. Fit review: public CoH UIs (e.g. ehomologados) remain observation-only citations; scraping or embedding them would create live-lookup authority this overlay forbids. Reuse stays inside TrustOS `promotion.compliance` + existing legal/tax packs.

## Safety

No live ehomologados scrape, no supplier contact, no credentials, no legal/tax conclusion, no second gate.
