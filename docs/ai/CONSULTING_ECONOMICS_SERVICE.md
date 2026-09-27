# Consulting Economics Service

## Purpose

`services.consulting_economics` is the product-agnostic adapter for consulting,
agency, professional-service, productized-research, retainer, milestone, and
recurring engagements. It accepts bounded offline inputs and delegates all
service economics arithmetic to `backend.economics.kernel.calculate_service_economics`.
It does not create a second kernel, service catalog, API, event spine, or live
commercial authority.

## Operator Entry Point

```python
from services.consulting_economics import build_consulting_economics_report

report = build_consulting_economics_report({
    "service_id": "research-sprint",
    "offering_name": "Productized Research Sprint",
    "service_model": "project",
    "currency": "USD",
    "package_price": {"amount": "4800", "currency": "USD", "evidence_state": "observed"},
    "internal_labor_hours": "36",
    "internal_labor_cost": {"amount": "1800", "currency": "USD", "evidence_state": "assumed"},
    "contractor_cost": {"amount": "600", "currency": "USD", "evidence_state": "observed"},
    "tooling_cost": {"amount": "120", "currency": "USD", "evidence_state": "assumed"},
    "pass_through_cost": {"amount": "80", "currency": "USD", "evidence_state": "observed"},
    "payment_fees": {"amount": "144", "currency": "USD", "evidence_state": "assumed"},
    "acquisition_cost": {"amount": "250", "currency": "USD", "evidence_state": "assumed"},
    "revision_support_reserve": {"amount": "200", "currency": "USD", "evidence_state": "assumed"},
    "delivery_hours": "40",
    "capacity_hours": "160",
    "evidence_mode": "manual",
    "evidence_id": "manual-research-sprint-v1",
    "source_ref": "manual://consulting-economics/research-sprint",
})
print(report.to_dict())
```

The module has no network, provider, credential, database, order, payment,
booking, message, publishing, or tenant-creation behavior. It is suitable for
fixture and manual evidence only. Local Python execution is not live commercial
validation.

## Contract

Supported `service_model` values are `project`, `retainer`, `milestone`, and
`recurring`. The same fields are used for goods-adjacent research, services,
hybrid engagements, and unknown offering names; no product-name branch changes
the calculation.

Money inputs are objects with an amount, currency, and optional provenance. An
explicit zero is a provided zero and is preserved in `explicit_zero_inputs`.
An omitted amount remains missing evidence. A currency mismatch is rejected
unless the value carries explicit `fx` provenance with rate, timestamp,
uncertainty, and source.

The adapter reports:

- contribution, contribution margin, contribution per delivery hour, and
  capacity metrics from the canonical `ServiceEconomics` result;
- minimum viable price as the canonical service fee less canonical contribution;
- break-even client count only when an explicit fixed monthly cost and positive
  canonical contribution are available;
- target monthly contribution and client value multiple through the kernel;
- conservative, base, upside, and downside scenario projections using visible,
  bounded planning sensitivities. These are assumptions, not market evidence;
- `acceptable`, `attractive`, `below_break_even`, `needs_evidence`, or `blocked`
  recommendations. No result guarantees profit.

## Missing Evidence

Missing labor, package price, delivery hours, or cost evidence causes the
scenario to remain `needs_evidence`. The adapter may call the canonical kernel
with an explicitly marked unavailable zero to preserve a bounded projection,
but the report retains the missing field and will not use the incomplete
projection as a complete recommendation. Missing capacity and client-value
inputs leave only their respective metrics unavailable. Acquisition data may be
unavailable for a service, but the report must say so and cannot call it live
validated.

## Authority Call Graph

```text
bounded request
  -> ConsultingEconomicsRequest normalization
  -> Money / EvidenceRef / explicit FX provenance
  -> backend.economics.kernel.calculate_service_economics
  -> evaluation.companyos.service_delivery.classify_client_value (when value exists)
  -> deterministic report and SHA-256 fingerprint
  -> TrustOS export_client_evidence (allowlisted client-safe projection only)
```

The adapter does not edit or replace the kernel, CompanyOS service catalog,
service-delivery authority, workspace registry, artifact store, or TrustOS
boundary.

## Client-Safe Output

Use `export_client_safe_report(report, workspace=..., registry=...)` only with an
already registered workspace. The helper delegates to TrustOS and exports only
`workspace_id`, status, blockers, evidence requirements, approvals required,
and next actions. Internal labor costs, formulas, scenario internals, source
references, and raw inputs are not exported.

## Validation

```powershell
python -m pytest -q tests/services/test_consulting_economics
python -m compileall -q services/consulting_economics tests/services/test_consulting_economics
```

The focused tests verify determinism, missing-versus-zero semantics, negative
input rejection, currency/FX provenance, utilization and capacity bounds,
product-agnostic service models, negative contribution, TrustOS isolation, and
no-live-action metadata.
