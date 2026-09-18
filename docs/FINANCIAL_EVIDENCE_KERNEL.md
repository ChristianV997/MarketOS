# Financial Evidence Kernel

`backend.economics.kernel` is the canonical typed boundary for new MarketOS
money, evidence, market-lane, unit-economics, and service-economics work. It
is offline and advisory; it does not authorize suppliers, ads, orders,
payments, publishing, or provider calls.

## Contracts

- `Money` stores `Decimal` amounts, an ISO currency, source, tax-inclusion
  state, provenance, and optional explicit FX evidence. Addition and
  subtraction reject mixed currencies. Conversions require a target currency,
  positive rate, timestamp, uncertainty, and source. The legacy static FX
  helper remains a compatibility adapter and is not used for new conversions.
- `EvidenceRef` keeps source, SKU/variant, origin/destination, capture and
  validity metadata, extraction method, evidence state, confidence, human
  confirmation, warnings, and snapshot identity. Unknown or missing evidence
  remains unknown and never becomes live or zero by inference.
- `MarketLane` carries origin, ship-from, warehouse, destination, currency,
  taxes, duties, brokerage, payment/platform/marketplace assumptions, returns,
  delivery, support, permissions, compliance, and evidence references.
- `UnitEconomicsAssumptions` and `UnitEconomicsResult` use exact Decimal
  arithmetic. They expose net sales; product, supplier, domestic and
  international costs; duty, tax, brokerage, payment/platform/marketplace/
  affiliate fees; return, defect, warranty, support, chargeback and FX
  reserves; CAC; contribution before and after CAC; margin; break-even and
  target CAC/ROAS; cash required per order; and refund-lag exposure.

Optional inputs are recorded in `missing_inputs` when absent. Their numeric
placeholder is an explicit assumed value for arithmetic only and does not
change the result's `evidence_state` from unknown.

## Formulas

The kernel applies a discount to price to obtain net sales. Duty is applied to
landed product and shipping cost. Tax is added only when the price is not
marked tax-inclusive. Percentage fees and reserves are applied to their
documented bases. Contribution before CAC is net sales less all non-CAC cost
lines; contribution after CAC subtracts CAC. Break-even CAC is the positive
contribution before CAC, and target CAC subtracts the target contribution
floor. ROAS values are net sales divided by the corresponding CAC where the
denominator is positive; otherwise they remain unknown.

Service economics uses the single catalog in
`evaluation.companyos.service_catalog` and the formulas:

```text
incremental_contribution = ad_spend * contribution_margin
                           * (ROAS_after - ROAS_before) - service_fee
orders_required_to_recover_fee = service_fee / (CAC_before - CAC_after)
```

The order-recovery result is unknown when CAC does not improve. Capacity
utilization is unknown when capacity is absent or zero.

## Compatibility and limits

`evaluation.economics`, supplier feasibility, the unit-economics service, and
the dry-run Commerce MVP adapt the kernel into their existing float-shaped
reports. This avoids breaking callers while preventing new formula copies.
CompanyOS service catalog IDs remain stable; canonical service names are
available through the existing catalog map aliases. No authentication,
tenant authorization, accounting authority, live FX feed, supplier
authorization, or external mutation is implemented by this kernel.
