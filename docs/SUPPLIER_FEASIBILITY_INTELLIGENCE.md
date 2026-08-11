# Offline Supplier Feasibility Intelligence

Supplier feasibility answers a different question from marketplace trend
intelligence:

- marketplace trends ask whether a product appears to have demand, pricing, or
  competition signals;
- supplier feasibility asks whether a candidate appears sourceable at a
  plausible cost, delivery window, inventory state, and fulfillment path.

This first slice is intentionally offline. It accepts synthetic snapshots and
sanitized manual CSV imports from CJ, Alibaba, AliExpress, Zendrop, AutoDS,
DSers, and Spocket. It does not call those providers, log in, scrape paid
dashboards, or claim live supplier proof.

## Run it

```powershell
python scripts/run_supplier_feasibility_intelligence.py --json
python scripts/run_supplier_feasibility_intelligence.py --markdown
python scripts/run_supplier_feasibility_intelligence.py `
  --manual-import tests/fixtures/supplier_feasibility/cj_manual_import.csv `
  --supplier cj `
  --markdown
python scripts/run_supplier_feasibility_intelligence.py `
  --output artifacts/supplier_feasibility/latest `
  --target-sell-price 29.99 `
  --markdown
```

The default is fixture/demo mode. `--output` writes only
`supplier_feasibility_report.json`, `supplier_feasibility_report.md`, and
`supplier_source_summary.json`.

## Evidence contract

Every field is provenance-aware: `fixture`, `manual_import`, `observed`,
`derived`, `assumed`, `unavailable`, `malformed`, `blocked`, or
`live_readonly`. A landed cost is derived only when unit cost and shipping cost
are both present. Missing shipping, inventory, delivery, MOQ, or variants stay
missing and become explicit risk flags.

The report includes:

- unit-cost and landed-cost confidence;
- inventory and fulfillment confidence;
- delivery speed and logistics risk;
- supplier rating/review reliability;
- MOQ and supplier-option penalties;
- margin feasibility proxy;
- break-even CPA and ROAS scenarios when a target selling price is supplied.

Fixture and manual values are not equivalent to authenticated CJ evidence. A
future credentialed validation may upgrade field provenance to `live_readonly`,
but it must remain explicitly gated through the existing CJ validation pack.

## Unit economics

For target selling price `P`, landed cost `L`, payment fee rate `p`, and
platform fee rate `f`:

```text
fees = P * (p + f)
gross_margin = P - L - fees
gross_margin_percent = gross_margin / P
break_even_cpa = max(0, gross_margin)
break_even_roas = P / break_even_cpa
```

The default assumptions are 2.9% payment fees and 5% platform fees. They are
scenario assumptions, not provider terms, and are shown in the JSON output.
Missing landed cost or selling price prevents a fabricated margin result.

## Supplier roles and boundaries

CJ fixture/validation-pack evidence is aligned with the existing authenticated
read-only path. Alibaba and AliExpress snapshots represent supplier-adjacent
catalog evidence. Zendrop, AutoDS, DSers, and Spocket inputs are manual imports
only in this slice. None of these sources authorizes orders, inventory writes,
fulfillment, supplier messages, payments, ads, or Shopify mutations.

## Product Validation Report

Pass the sanitized report into the existing client-facing report:

```powershell
python scripts/generate_product_validation_report.py `
  --supplier-feasibility-report artifacts/supplier_feasibility/latest/supplier_feasibility_report.json `
  --markdown
```

The report adds Supplier Feasibility Signals, landed-cost context, shipping and
delivery risk, supplier reliability, and break-even scenario data. If no report
is supplied it emits `supplier_feasibility_not_supplied` and keeps the existing
supplier-proof blocker.

## Safety

No credentials, raw provider payloads, raw HTML, paid-dashboard exports,
browser traces, or private client data belong in these inputs. Paths are local
JSON/CSV only and traversal is rejected. All generated reports assert
`read_only=true`, `network_calls=false`, and `mutated=false`.

## Relationship to consumer attention

Consumer attention evidence can add hooks, pain points, objections, and UGC
hypotheses to the same client report. It answers whether a product may be
marketable; this supplier layer answers whether it may be sourceable. Keep the
two scores separate. Neither fixture/manual score is live supplier proof, and
consumer evidence never authorizes ad spend or publishing.

Product Opportunity Synthesis uses this layer for landed cost, margin,
delivery, inventory, and supplier-risk decisions. Missing or fixture-only
supplier fields keep `supplier_validation_required=true` and prevent a claim
of live sourcing proof.
