# Stack Planner (`backend/stack_planner`)

Recommends a commerce/payment/automation stack for a business, applies hard
cost-governance rules, and returns the resulting cost/margin/break-even
numbers — composing `backend/providers` and `backend/costs`, never
reimplementing fee or margin math (see `docs/COST_AWARE_INTEGRATION_AUDIT.md`).
Purely advisory: `recommend_stack` never mutates state or spends money, so
it does not go through `backend.workspaces.live_mode_checklist` (unlike
`services.ecommerce_operator.launch_guard`, which gates real actions).

## The 7 strategy presets

All 7 are reachable as of Phase 2. The e-commerce strategies return
`commerce_provider_recommendation`/`payment_provider_recommendation`; the
lead-gen/agency strategies instead return `crm_provider_recommendation`
(no checkout involved) — see `_recommend_ecommerce_stack`/`_recommend_lead_gen_stack`
in `backend/stack_planner/planner.py`.

| Strategy | Notes |
|---|---|
| `own_ecommerce_low_cost` | Hostinger + WooCommerce + Mercado Pago/Stripe MX — the default |
| `client_ecommerce_low_cost` | Same stack, client-facing |
| `client_ecommerce_shopify_premium` | Shopify, only when `margin_sensitivity != "low_cost_validation"` |
| `marketos_owned_stack` | Medusa, self-hosted |
| `high_ticket_lead_gen_low_cost` | Chatwoot (conversation) + Mautic (marketing automation); CRM gap reported honestly (`crm_provider_recommendation.blocked=True`) — Twenty is AGPL-3.0 and deferred pending legal review, not recommended |
| `high_ticket_lead_gen_gohighlevel_fast` | GoHighLevel (bundles CRM+conversation+automation), only above its revenue threshold |
| `agency_white_label_fast` | GoHighLevel, only above its (higher, agency-tier) revenue threshold |

Lead-gen/agency strategies skip `margin_after_stack_cost`/`break_even_client_price`
(left at zero with an explicit note) — those strategies are priced
per-lead/retainer, not per-unit, so `backend.validation.margin_calculator`'s
per-order formula doesn't apply.

## Hard rules (`backend/stack_planner/recommendations.py`)

| Rule | Function | Behavior |
|---|---|---|
| No GoHighLevel below its revenue threshold | `gohighlevel_allowed` | blocked with reason until `expected_monthly_revenue_usd` clears the cheapest GoHighLevel plan's `min_monthly_revenue_usd` |
| No Shopify when WooCommerce is sufficient and margin-sensitive | `shopify_allowed_over_woo` | blocked when `margin_sensitivity == "low_cost_validation"` |
| n8n never for a white-labeled client-facing product | `n8n_allowed` | blocked when `is_white_labeled_client_facing` is `True` — n8n stays internal-only per `docs/oss/LICENSE_MANIFEST.yml` |
| Postiz never without legal approval | `postiz_allowed` | blocked unless `postiz_legal_approval=True` |
| No Twenty CRM recommendation, ever, this pass | `build_crm_recommendation` | Twenty (AGPL-3.0) stays deferred pending legal review by explicit prior user decision — `high_ticket_lead_gen_low_cost` reports the gap honestly instead of recommending it |

Blocked providers are still returned in `automation_recommendations` (or
`crm_provider_recommendation` for lead-gen strategies) with `blocked=True`
and a `blocked_reason` — never silently omitted.

## Example

```
python -m marketos.cli stack recommend \
  --business-model own_ecommerce --target-geo MX \
  --expected-monthly-revenue 5000 --margin-sensitivity low_cost_validation \
  --supplier-cost 10 --retail-price 35 --json
```

Returns a `BusinessStackRecommendation`: `commerce_provider_recommendation`
(WooCommerce), `payment_provider_recommendation` (Mercado Pago MX —
regionally preferred and marginally cheaper than Stripe MX in the current
catalog), `automation_recommendations` (n8n allowed for internal ops,
GoHighLevel and Postiz blocked with reasons), `monthly_cost_estimate`
(fixed + payment fees), `margin_after_stack_cost`, `break_even_client_price`.

## CLI / API

- `python -m marketos.cli stack recommend ...` / `POST /api/stack/recommend` —
  lighter, non-billable utility, no `CommercialRunEnvelope`/audit log.
- `python -m marketos.cli services profit-stack-advisor ...` /
  `POST /api/services/profit-stack-advisor` — the sellable, audited variant
  (see `docs/SERVICE_MODULES.md`'s Profit Stack Advisor section).
