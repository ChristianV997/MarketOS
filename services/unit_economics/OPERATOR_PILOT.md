# Unit Economics — Low-Risk Service Pilot Operator Guide

Offline, supervised pilot for `services.unit_economics`. This service performs
deterministic margin/break-even/ROAS diagnostics only. It does not execute ads,
orders, payments, provider calls, or any external mutation.

## Prerequisites

- Python 3.12 (repository-supported toolchain)
- Local MarketOS checkout on branch `cursor/marketos-low-risk-service-pilot-v1`
- No credentials, network access, or live commerce data required for the pilot path

## Command sequence

```bash
python -m pytest -q tests/services/test_unit_economics/
python - <<'PY'
from services.unit_economics.analyzer import run_unit_economics
result, envelope = run_unit_economics(
    "Widget",
    supplier_cost=10.0,
    retail_price=40.0,
    shipping_cost=2.0,
)
print(result.verdict, result.break_even_cac, envelope.status, result.deterministic_fingerprint())
PY
```

## Inputs

| Field | Requirement |
| --- | --- |
| `product_name` | Non-empty string |
| `supplier_cost` | Finite number `>= 0` |
| `retail_price` | Finite number `>= 0` |
| `shipping_cost` | Finite number `>= 0` (default `0`) |
| `category` | Optional category label (default `general`) |
| `geo` | Optional geo code; geo margin computed only when provided |
| `workspace` | Optional `ClientWorkspace`; defaults to dry-run internal workspace |

## Outputs

- `UnitEconomicsResult` JSON-serializable dict via `to_dict()`
- `CommercialRunEnvelope` with `mode=dry_run`, `proposed_spend=0`, `actual_spend=0`
- Artifact saved under workspace artifact store as `result.json` when available
- `deterministic_fingerprint()` for replay comparison (excludes timestamps and experiment ids)

## Status semantics

| Envelope status | Meaning |
| --- | --- |
| `completed` | Valid inputs; economics computed offline |
| `blocked` | Invalid inputs rejected before margin math |

| Result verdict | Meaning |
| --- | --- |
| `profitable` / `breakeven` / `loss` | Implemented margin-calculator outcome |
| `invalid_input` | Service-boundary validation failed |
| `unknown` | Margin calculator unavailable or returned no status |

## Safety boundaries

- `dry_run=true` by default
- No provider activation
- No order/payment/ad/customer-message authority
- No GitHub or workspace mutation beyond local artifact persistence
- Human review required before any downstream launch or spend decision

## Evidence classes

| Class | Example in this pilot |
| --- | --- |
| Implemented + tested | `run_unit_economics` margin math on valid fixtures |
| Simulated | Default ledger projection values when ledger history is empty |
| Unavailable | Live ad spend, orders, supplier APIs |
| Not executed | Worker dispatch, provider calls, commerce mutations |

## Troubleshooting

| Symptom | Cause | Action |
| --- | --- | --- |
| `invalid_input` / blocked envelope | Empty name or negative cost | Fix inputs and rerun |
| `unknown` verdict with empty margins | Upstream calculator failure | Inspect logs; service still returns safely |
| Different experiment ids, same fingerprint | Expected on duplicate runs | Use fingerprint for economics replay, not experiment id |
| `from_ledger` differs from direct run | Ledger snapshot unavailable | Treat as fixture/default evidence, not live proof |

## Why this wrapper does not execute workers

`run_unit_economics` only composes existing offline calculators and writes
planning artifacts. It registers a `CommercialRunEnvelope` for auditability but
never sets execution authority, spend authorization, or provider activation.
