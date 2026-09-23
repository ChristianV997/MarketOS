# Geographic Opportunity Analysis

`services/geographic_opportunity/` -- an offline, manual-first geographic
price-asymmetry and trade-feasibility evidence service for consulting
research. It composes existing canonical authorities; it does not
introduce a second unit-economics engine or a live trade-data client.

This is a **greenfield module**: a repo-wide search before writing it
found no existing trade-flow, UN Comtrade, HS-code, bilateral-trade,
country-pair, or canonical-geography concept anywhere in this
repository, and no precedent for OR-Tools or SimPy (neither is a
declared dependency nor used anywhere), so neither was introduced here.

## What it is

Given one candidate-bound cross-country opportunity (goods, service, or
hybrid, for a known or unknown origin/destination pair),
`build_geographic_opportunity_report(offer, generated_at=...)` returns a
deterministic `GeographicOpportunityReport`:

- `landed_cost_scenarios` -- three named scenarios (`base`, `best_case`,
  `worst_case`), each a `backend.economics.kernel.UnitEconomicsResult`
  produced by `calculate_unit_economics` (never re-derived here). Only
  produced for goods/hybrid offerings with both a destination price and
  an origin supplier cost.
- `comparison` -- a `DestinationSourceComparison`: the destination/origin
  price gap (only computed when both sides share one currency), the
  trade unit-value proxy, and whether that proxy conflicts with the
  supplier's own quoted cost by more than 25%.
- `risk_matrix` -- one `OpportunityRiskEntry` per evidence-backed
  dimension, severity derived directly from that dimension's own
  evidence quality.
- `next_actions` -- recommended next research actions for every `high`
  or `blocked` risk entry, plus a dedicated action when the unit-value
  proxy and supplier cost conflict.
- `blockers` / `evidence_gaps` -- plain-text findings, always including
  an unknown-geography or unknown-offering blocker when applicable.
- `status` -- from `services.status.commercial_status()`.
- `read_only=True`, `network_calls=False`, `mutated=False` -- hard
  invariants enforced by `__post_init__`, not just documented. No UN
  Comtrade API call, supplier contact, or import order is reachable from
  this module.

## What it composes (not duplicates)

| Concept | Source | How it's used here |
|---|---|---|
| Money, currency validation | `backend.economics.kernel.Money` | every price/cost/fee field |
| Evidence identity | `backend.economics.kernel.EvidenceRef` | attached to `FieldEvidence` when a field is evidence-backed |
| Lane/tax/duty assumptions | `backend.economics.kernel.MarketLane` | required whenever `geography_kind="known"`; supplies destination geography |
| Landed-cost math | `backend.economics.kernel.calculate_unit_economics` | called once per scenario in `report.py`; math is never re-derived |
| FX provenance | `backend.economics.kernel.Money.exchange_rate`/`exchange_rate_timestamp`/`source` | reused as-is; no richer FX-evidence concept exists anywhere else in this repository (confirmed by search) |
| Existing supplier feasibility | `evaluation.commerce.supplier_feasibility` | precedent for the offline, no-live-call unit-economics composition pattern this service follows |
| Secret/HTML detection | `backend.adapters.research.supplier_feasibility` (`SECRET_KEY`/`SECRET_VALUE`/`HTML_MARKERS`) | re-declared verbatim in both `services/geographic_opportunity/controls.py` and `backend/adapters/research/trade_flows.py`, matching this repo's own established per-module duplication convention for this check |
| Service status labels | `services.status.commercial_status` | `GeographicOpportunityReport.status` |

The evidence-quality vocabulary, missing-vs-explicit-zero helpers, and
goods/service/hybrid/unknown offering-kind gating are modeled after (not
imported from) a sibling service built in an earlier, still-unmerged
branch of this repository -- that module is not reachable from this
branch, so this is a from-scratch re-declaration of the same proven
design pattern, not a shared import.

## `backend/adapters/research/trade_flows.py` -- the pinned UN Comtrade adapter

This is a new file (it did not exist before this change). It is an
**offline-only, pinned bulk-file adapter**: no HTTP client, no
authentication, no live API call to `comtradeapi.un.org` or anywhere
else. It reads a manually-downloaded UN Comtrade bulk-download file
(JSON or CSV) already saved to local disk and normalizes it into plain,
sanitized dicts.

"Pinned" means it recognizes exactly the field names UN Comtrade's own
bulk-download files are documented to use as of this writing
(`reporterISO`/`partnerISO`/`cmdCode`/`period`/`primaryValue`/`netWgt`/
`qtyUnitAbbr`/`qty`, plus a small set of common export-tool variants) and
aliases nothing beyond that narrow, explicit list -- an unrecognized
column is left absent, never guessed at.

It returns **plain dicts**, not `services.geographic_opportunity`
dataclasses: no file under `backend/**` imports from `services/**`
anywhere in this repository (confirmed by a repo-wide grep before
writing this file), so mapping a normalized record into a
`BilateralTradeFlowObservation` is a caller-side concern in the service
layer, not this adapter's.

Modeled directly on `backend.adapters.research.supplier_feasibility`'s
own offline-importer pattern (`validate_input_path`, secret/HTML
rejection before any parsing, `client_safe_offer`-equivalent
projection) -- re-declared, not imported, matching that module's own
documented convention for this exact check.

## Modeled concepts and their dataclasses

| Mission concept | Dataclass / field |
|---|---|
| Cross-country demand/supply asymmetry | `report.DestinationSourceComparison` (derived output, not an input) |
| Bilateral trade flows | `schemas.BilateralTradeFlowObservation` |
| HS-code observations | `schemas.CandidateBoundTradeIdentity.hs_code` + `BilateralTradeFlowObservation`'s own evidence |
| Unit-value proxies | `BilateralTradeFlowObservation.unit_value` -- explicitly documented as a customs-statistics proxy, never a retail price or a supplier quote |
| Destination price observations | `schemas.DestinationPriceObservation` (`price_type`, `is_realized_sale` defaulting `False`) |
| Freight and duty assumptions | `schemas.FreightDutyAssumptions` |
| Marketplace fees | `TradeOpportunityOffer.marketplace_fee_rate` + its own `FieldEvidence` |
| Returns and lead-time assumptions | `schemas.ReturnsLeadTimeAssumptions` |
| Service-delivery capacity by geography | `schemas.ServiceCapacityByGeography` (`capacity_available: bool \| None`) |
| FX provenance | `Money.exchange_rate`/`exchange_rate_timestamp`/`source`, enforced via `controls.require_fx_provenance` |
| Regulatory and compliance blockers | `schemas.RegulatoryComplianceObservation` -- `status` can never be an affirmative clearance (see below) |

## The ten required adversarial cases

Each is a dedicated test class in `tests/services/test_geographic_opportunity/test_report.py`:

1. **Attractive price gap erased by freight** -- `TestAttractivePriceGapErasedByFreight`: a large raw price gap (120 − 55) is eroded by heavy freight/duty in the worst-case scenario; contribution provably drops.
2. **Attractive trade flow with no retail evidence** -- `TestAttractiveTradeFlowWithNoRetailEvidence`: present trade-flow evidence plus missing destination-price evidence produces an explicit blocker naming exactly that gap.
3. **Missing duty** -- `TestMissingDuty`: see the dedicated section below.
4. **Missing supplier cost** -- `TestMissingSupplierCost`: `origin_supplier_cost=None` produces zero landed-cost scenarios and a named blocker.
5. **Currency mismatch** -- `TestCurrencyMismatch`: a destination price in a different currency than the origin cost raises `CurrencyMismatchError`.
6. **Stale or conflicting country observations** -- `TestStaleOrConflictingCountryObservations`: `quality="stale"`/`"conflicting"` evidence is flagged `"high"` severity.
7. **Service capacity unavailable** -- `TestServiceCapacityUnavailable`: `capacity_available=False` is a blocker; `capacity_available=None` (never confirmed either way) is an evidence gap, not a blocker -- the two are deliberately distinct.
8. **Unknown geography** -- `TestUnknownGeography`: `geography_kind="unknown"` produces a single blocker and nothing else (no scenarios, no comparison, no risk matrix).
9. **Explicit zero versus missing** -- `TestExplicitZeroVersusMissing`: `duty_rate=Decimal("0")` is used as a real zero in the scenario math; `duty_rate=None` is tracked as missing (subject to the kernel-fallback caveat below).
10. **Unsupported regulatory inference** -- `TestUnsupportedRegulatoryInference`: `RegulatoryComplianceObservation.status` structurally cannot be an affirmative clearance value (`"compliant"`, `"cleared"`, `"approved"`, ... all raise `EconomicsError` at construction), and `controls.reject_unsupported_regulatory_claim` re-verifies this at the export boundary.

Two additional negative controls beyond the ten, directly required by
the mission's "do not treat" list, each with their own test classes:
**trade unit value is never used as the landed-cost price input** or
treated as a retail price (`TestUnitValueProxyIsNeverTreatedAsRetailPriceOrCost`), and **a public listing price is never treated as a realized
sale** (`TestListingPriceIsNeverTreatedAsRealizedSale` -- `is_realized_sale` defaults `False` and every landed-cost scenario's own
`assumptions_note` discloses the `price_type` it was built on).

## A documented kernel limitation: "missing duty" and the landed-cost math itself

`backend.economics.kernel.calculate_unit_economics` itself falls back to
`lane.duty_rate`/`lane.tax_rate`/`lane.marketplace_fee_rate` whenever the
corresponding `UnitEconomicsAssumptions` field is `None` **and** a lane
is supplied. `MarketLane.duty_rate`/`tax_rate` always default to
`Decimal("0")` when a caller didn't set them explicitly -- the kernel
itself cannot distinguish "the lane confirms 0%" from "nobody ever set
this." Because `geography_kind="known"` requires a lane, this means
`UnitEconomicsResult.missing_inputs` can **never** show `"duty_rate"` as
missing once a lane is present, even when this service's own
`FreightDutyAssumptions.duty_rate` is `None`.

This is an existing, unavoidable kernel convention (already documented
identically for the same reason in a sibling, still-unmerged service in
this repository) -- this module does not re-derive or work around it,
since doing so would mean reimplementing kernel math, which it must
never do. Instead, the enforcement of "never treat a missing duty rate
as zero" lives one layer up, at this service's own evidence/reporting
boundary: `report._risk_matrix`/`report._blockers` flag a
`quality="missing"` `freight_duty` evidence as `"blocked"` severity and
surface it as a named blocker, **regardless of what number the
underlying kernel math had to assume**. `TestMissingDuty` proves this
exact behavior rather than asserting on `missing_inputs`, and documents
why in its own test docstring.

## Limitations and exact provenance

- **Newly written in this change:** `schemas.py`, `controls.py`,
  `report.py`, `export.py`, `__init__.py`,
  `backend/adapters/research/trade_flows.py`, all tests, all fixtures,
  this document.
- **Composed, not duplicated:** `Money`/`EvidenceRef`/`MarketLane`/
  `UnitEconomicsAssumptions`/`UnitEconomicsResult`/
  `calculate_unit_economics` (kernel), `commercial_status`
  (`services.status`). The secret/HTML regex convention is re-declared
  verbatim per this repository's own established per-module duplication
  style (see the table above for exact sources).
- **Not implemented:** no live UN Comtrade API client (deliberately --
  the mission requires no live calls); no OR-Tools/SimPy-based
  optimization or simulation (no existing precedent or concrete scenario
  in this change justified adding either as a new dependency); no
  canonical ISO-3166 country/region validation (none exists anywhere in
  this repository to build against -- country identifiers are free text,
  matching `MarketLane`'s own convention).
- **Client-safe export** (`export.build_client_safe_export`) is
  self-contained: this service has no TrustOS/workspace dependency of
  its own. "Client-safe" here means curated, already-generated content
  by default, with raw evidence notes included only when explicitly
  requested and only after passing `controls.reject_unsafe_input`.
- **Known kernel-inherited limitation:** see the dedicated section above
  on `missing_inputs` and lane-level duty/tax/marketplace-fee defaults.
