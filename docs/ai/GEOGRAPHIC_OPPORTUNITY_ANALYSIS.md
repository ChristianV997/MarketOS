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

## CLI entry point, offline serialization, and portfolio compatibility

Three modules were added in a later finalization pass, strengthening
the original build without altering its boundaries: no live Comtrade
client, no credentials, no provider activation, and
`backend.economics.kernel` remains untouched and the sole economics
authority.

- **`serialization.py`** -- deterministic, offline JSON-dict loaders
  culminating in `offer_from_dict`, the sole entry point `cli.py` uses
  to load an operator-authored offer file. `money_from_dict` and
  `evidence_ref_from_dict` are thin pass-throughs to
  `backend.economics.kernel.Money.from_dict` /
  `EvidenceRef.from_dict` (which already existed in the kernel) --
  this module never re-derives that logic. `lane_from_dict` is
  deliberately a **bounded, practical subset** of `MarketLane`'s full
  ~19-field shape (`lane_id`, `origin`, `ship_from`, `warehouse`,
  `destination_country`, `destination_region`, `currency`, `tax_rate`,
  `duty_rate`) -- the fields this domain's own fixtures actually vary
  -- not a full `MarketLane` round-trip serializer. Every validation
  (currency matching, offering/geography-kind gating,
  missing-vs-explicit-zero, regulatory-status vocabulary, ...) still
  happens inside each dataclass's own `__post_init__`; this module
  performs none of its own.
- **`cli.py`** -- a deterministic, offline operator entry point
  (`python -m services.geographic_opportunity.cli OFFER.json
  --generated-at ... [--format json|markdown]`). Reads one local offer
  JSON file, builds a report via
  `report.build_geographic_opportunity_report`, and prints JSON or
  Markdown. `--generated-at` is required (never defaults to the system
  clock), keeping a given invocation reproducible from its inputs
  alone. Performs no network I/O and writes nothing but an
  explicitly-requested `--output` file.
- **`portfolio.py`** -- a duck-typed adapter onto the existing, merged
  `backend.organization.portfolio_report.build_portfolio_report`
  (which reads only `.report_id` / `.service_name` / `.status` /
  `.recommendations` / `.next_actions` / `.risk_flags` off each entry
  it is given -- confirmed by reading that module before writing this
  one; it performs no `isinstance` check). This lets this service's
  own reports be aggregated into a cross-service `PortfolioReport`
  alongside reports from other services (e.g. an "opportunity
  discovery" service) without either side importing the other's
  dataclasses, and without this module importing any unmerged
  "opportunity discovery" branch -- it depends only on this service's
  own `GeographicOpportunityReport`.
- **Explicit FX provenance is now enforced, not just available.**
  `controls.require_fx_provenance` existed from the original build but
  was not called anywhere; `report._build_comparison` and
  `report._landed_cost_scenarios` now call it on every `Money` that
  could reach a comparison or landed-cost scenario, so a `Money` that
  already carries a currency conversion (`exchange_rate` set) without
  an acceptable, explicit rate source is rejected
  (`controls.FxProvenanceError`) before a report is ever produced. A
  `Money` with no `exchange_rate` at all (the common, unconverted case)
  always passes unchanged.
- **Broader fixture-to-report integration.** Four full offer fixtures
  (`tests/fixtures/geographic_opportunity/offers/{goods,service,hybrid,unknown}_offer.json`)
  are loaded through `serialization.offer_from_dict` and driven all the
  way through `build_geographic_opportunity_report` in
  `tests/services/test_geographic_opportunity/test_serialization.py`,
  alongside dedicated `cli.py` and `portfolio.py` test files.
- **An explicit kernel-behavior regression test.**
  `TestKernelDutyRateFallbackIsNeverReportedAsMissing` in
  `test_report.py` calls
  `backend.economics.kernel.calculate_unit_economics` directly (no
  `services.geographic_opportunity` code involved) to lock in the
  kernel's own duty-rate lane-fallback convention described below --
  distinct from `TestMissingDuty`, which proves this service's own
  blocker workaround.

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

- **Newly written in the original build:** `schemas.py`, `controls.py`,
  `report.py`, `export.py`, `__init__.py`,
  `backend/adapters/research/trade_flows.py`, all tests, all fixtures,
  this document.
- **Newly written in this finalization pass:** `serialization.py`,
  `cli.py`, `portfolio.py`, four full-offer fixtures under
  `tests/fixtures/geographic_opportunity/offers/`,
  `tests/services/test_geographic_opportunity/{test_serialization,test_cli,test_portfolio}.py`,
  plus additional test classes in `test_report.py` (FX-provenance
  enforcement, the kernel duty-rate regression guard, supplier-cost-
  vs-unit-value separation) and `test_export.py` (client-safe export
  coverage). `report.py` and `schemas.py` gained the FX-provenance
  enforcement described above; `backend/economics/kernel.py` was not
  modified.
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
