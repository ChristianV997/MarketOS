# Supplier & Logistics Research Service

`services/supplier_logistics_research/` -- a product-agnostic supplier and
logistics **evidence** service for consulting reports. It composes
existing canonical authorities; it does not introduce a second supplier
scorer or a second logistics authority.

## What it is

Given one candidate-bound supplier/logistics offer (goods, service, or
hybrid), `build_supplier_logistics_report(offer, generated_at=..., target_price=None)`
returns a deterministic `SupplierLogisticsReport`:

- `landed_cost_scenarios` -- three named scenarios (`base`, `best_case`,
  `worst_case`), each a `backend.economics.kernel.UnitEconomicsResult`
  produced by `calculate_unit_economics` (never re-derived here).
- `risk_matrix` -- one `RiskMatrixEntry` per evidence-backed dimension
  (quoted cost, supplier identity, logistics, MOQ/availability, lead
  time, customs/duty/tax, shipping, returns/defects, service capacity),
  severity derived directly from that dimension's own evidence quality.
- `next_actions` -- recommended verification actions for every `high` or
  `blocked` risk entry.
- `blockers` -- plain-text blockers, always including a missing-price or
  missing-evidence blocker, or (for an unknown offering) the single
  "must remain unassessed" blocker.
- `evidence_quality_summary` -- counts per `EVIDENCE_QUALITY` label.
- `status` -- from `services.status.commercial_status()`, the shared
  7-label service-maturity status (not a per-offer confidence score).
- `read_only=True`, `network_calls=False`, `mutated=False` -- hard
  invariants enforced by `SupplierLogisticsReport.__post_init__`, not
  just documented. No live provider, supplier contact, order, payment,
  or shipping action is reachable from this module.

## What it composes (not duplicates)

| Concept | Source | How it's used here |
|---|---|---|
| Money, currency validation | `backend.economics.kernel.Money` | `quoted_price`, all shipping/customs Money fields |
| Evidence identity | `backend.economics.kernel.EvidenceRef` | attached to `FieldEvidence` when a field is evidence-backed |
| Lane/tax/duty assumptions | `backend.economics.kernel.MarketLane` | optional `SupplierLogisticsOffer.lane`; supplies destination geography and lane-level duty/tax fallback |
| Landed-cost math | `backend.economics.kernel.calculate_unit_economics` | called once per scenario in `report.py`; math is never re-derived |
| Supplier offer identity | `evaluation.commerce.canonical.SupplierOfferIdentity` | wrapped in `CandidateBoundSupplierIdentity` (adds the missing candidate binding) |
| Risk-severity vocabulary style | `evaluation.commerce.canonical.RiskState`, `evaluation.commerce.fulfillment_risk_lifecycle` | `RISK_SEVERITIES = {low, medium, high, blocked}` mirrors `RiskState.level`; the 25-state order-fulfillment lifecycle itself is intentionally **not** imported -- this service assesses pre-order evidence, not an order in flight |
| Secret/HTML detection | `backend.adapters.research.supplier_feasibility` (`SECRET_KEY`/`SECRET_VALUE`/`HTML_MARKERS`) | re-declared verbatim in `controls.py`, matching this repo's own per-module duplication convention for this check |
| Cross-client leakage markers | `evaluation.companyos.service_delivery` (`_LEAK_MARKERS`) | convention mirrored (not imported) in `controls.py`'s `_CROSS_CLIENT_MARKERS` |
| Service status labels | `services.status.commercial_status` | `SupplierLogisticsReport.status` |

Nothing in this service re-implements `evaluation.commerce.supplier_feasibility`
(the existing supplier scorer) or introduces a competing logistics
authority. It is a read-only evidence-composition layer above those
existing authorities and the kernel.

## Evidence model

Every reported field carries a `FieldEvidence(quality, evidence_ref,
observed_at, note)`. `quality` is one of `EVIDENCE_QUALITY = {observed,
manual, fixture, stale, missing, conflicting}` -- deliberately distinct
from `backend.economics.kernel.EVIDENCE_STATES` (which classifies a
`Money`/`EvidenceRef`'s own state, not "how good is this one reported
field").

**Missing vs. explicit zero.** Every optional numeric field is typed
`Decimal | None` / `int | None` and defaults to `None`. A caller must
pass an actual `Decimal("0")` to record a confirmed zero (e.g. a
duty-free HS code); nothing in this module invents a zero for an unknown
field. `report.py`'s scenario composition follows the same rule: an
unknown rate stays `None` through `calculate_unit_economics`, which
tracks it in `UnitEconomicsResult.missing_inputs` rather than silently
assuming zero.

**Goods: supplier proof, customs proof, and logistics proof stay
separate.** `GoodsLogisticsProfile` carries three independent
`FieldEvidence` records (`supplier_evidence`, `customs.evidence`,
`logistics_evidence`) plus per-dimension evidence on MOQ/availability,
lead time, returns/defects, and shipping -- never one blended "evidence"
field. A report can show "supplier identity observed, customs rate
conflicting, shipping cost manual claim" as three distinct facts.

**Services: capacity is an assumption, never a verification.**
`ServiceCapacityProfile` models weekly capacity hours, delivery
hours/unit, business hours, `subcontractor_dependency`,
`sla_assumption`, and `geographic_coverage` -- all attached to one
`FieldEvidence`. This module never contacts the provider, so the
severity of the `service_capacity` risk entry is driven purely by that
evidence's own `quality`; an unconfirmed claim can never read as `low`
severity / verified.

**Hybrid offerings preserve both components.** `offering_kind="hybrid"`
requires both `goods` and `service` to be present; the risk matrix and
(goods-driven) landed-cost scenarios cover both.

**Unknown offerings remain unassessed.** `offering_kind="unknown"`
forbids both `goods` and `service` (enforced in
`SupplierLogisticsOffer.__post_init__`). `build_supplier_logistics_report`
short-circuits such an offer to a single blocker and empty
scenarios/risk-matrix/next-actions -- there is no partial assessment
path.

**Candidate-bound identity.** `SupplierOfferIdentity` alone carries no
candidate binding. `CandidateBoundSupplierIdentity` makes that binding
required, and `SupplierLogisticsReport.__post_init__` re-checks that its
own `candidate_id` matches `offer.identity.candidate_id`.

**Verified means one specific thing.** `controls.is_verified(evidence)`
is the single gate: only `quality="observed"` backed by an
`evidence_ref` that is `human_confirmed=True` with `evidence_state` in
`{verified, observed, live_readonly}` counts as verified. A supplier's
own claim (`quality="manual"`, or any unconfirmed `evidence_ref`) is
never promoted to verified by this module or anything that consumes it.

## Landed-cost scenarios

`report._build_assumptions` builds a `UnitEconomicsAssumptions` per
scenario from the offer's `customs`/`returns_defects`/`shipping`
profiles. `base` uses each known value unchanged. `best_case` and
`worst_case` perturb **only** rates whose own evidence `quality` is
`manual` or `fixture` (±15%, clamped to `[0, 1]`) -- an `observed`
(confirmed) rate never moves, and a missing (`None`) rate never moves
either; sensitivity analysis is applied to known-but-uncertain values,
never invented for an unknown one.

If a known `duty_rate`/`tax_rate` is missing on the offer's own
`CustomsDutyTaxProfile`, the scenario falls back to the `MarketLane`'s
`duty_rate`/`tax_rate` when a lane was supplied -- note that
`MarketLane` itself defaults those to `Decimal("0")` when its caller
didn't set them explicitly (an existing kernel convention, not something
this service can distinguish from "confirmed zero" once inherited from
the lane).

`target_price` is optional. When supplied, it must share the offer's
quoted-price currency (`CurrencyMismatchError` otherwise, checked via
`controls.require_matching_currency` before scenario composition). When
omitted, each scenario's `price` argument to `calculate_unit_economics`
is the quoted supplier cost itself -- a **cost-basis-only** stand-in, so
`contribution_before_cac`/`contribution_after_cac` read as the total
landed-cost burden added on top of the quoted cost, not a real margin
projection. Every such scenario's `assumptions_note` discloses this
explicitly.

Only `goods` and `hybrid` offers (via their `goods` component) produce
landed-cost scenarios; a `service`-only offer produces none.

## Negative controls (`controls.py`)

| Control | Function | Mechanism |
|---|---|---|
| Credential-shaped input | `contains_secret` / `reject_unsafe_input` | `SECRET_KEY`/`SECRET_VALUE` regex, copied verbatim from `backend.adapters.research.supplier_feasibility` |
| Raw HTML | `contains_html` / `reject_unsafe_input` | `HTML_MARKERS` regex, copied verbatim from the same adapter |
| Cross-client fields | `contains_cross_client_reference` / `reject_unsafe_input` | marker list mirroring `evaluation.companyos.service_delivery._LEAK_MARKERS`'s convention |
| Mismatched currency | `require_matching_currency` | raises `backend.economics.kernel.CurrencyMismatchError`; also enforced structurally in `SupplierLogisticsOffer.__post_init__` (lane vs. quoted price) and `report.build_supplier_logistics_report` (target price vs. quoted price) |
| Missing money | `require_present` | raises `NegativeControlError` on `None`; `report.py` itself never fabricates a scenario when `quoted_price` is `None` |
| Supplier claim mistaken for verified evidence | `is_verified` | the single verification gate described above |

## Limitations and exact provenance

- **Newly written in this change:** `schemas.py`, `controls.py`,
  `report.py`, `__init__.py`, all tests, all fixtures, this document.
- **Composed, not duplicated:** `Money`/`EvidenceRef`/`MarketLane`/
  `UnitEconomicsAssumptions`/`UnitEconomicsResult`/
  `calculate_unit_economics` (kernel), `SupplierOfferIdentity`
  (canonical), `commercial_status` (services.status). The secret/HTML
  regex and cross-client marker conventions are re-declared verbatim per
  this repository's own established per-module duplication style for
  those specific checks (see the table above for exact sources).
- **Not implemented:** no HTTP client, no file-import path (unlike
  `backend.adapters.research.supplier_feasibility`, this service takes
  in-memory dataclasses only -- a caller wiring in file-based evidence
  must validate/read the file itself, e.g. reusing
  `scripts/research_to_decision.py`'s secure-read pattern, before
  constructing a `SupplierLogisticsOffer`).
- **Not tested beyond focused pytest:** no integration test against a
  real product-research pipeline; no live-data validation (there is no
  live-data path to validate -- this service is offline by construction).
- **Sensitivity-scenario limitation:** the ±15% best/worst-case
  perturbation is a fixed, documented heuristic, not a statistically
  derived confidence interval -- it exists to make `best_case`/
  `worst_case` scenarios differ meaningfully for uncertain-but-known
  values without ever inventing a number for a genuinely unknown one.
- **Lane duty/tax zero-default inheritance:** documented above under
  Landed-cost scenarios; this is an existing `MarketLane` convention
  this service inherits, not something introduced here.
