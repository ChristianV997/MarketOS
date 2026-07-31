# Stack Planner (`backend/stack_planner`)

Recommends a commerce/payment/automation stack for a business, applies hard
cost-governance rules, and returns the resulting cost/margin/break-even
numbers — composing `backend/providers` and `backend/costs`, never
reimplementing fee or margin math (see `docs/COST_AWARE_INTEGRATION_AUDIT.md`).
Purely advisory: `recommend_stack` never mutates state or spends money, so
it does not go through `backend.workspaces.live_mode_checklist` (unlike
`services.ecommerce_operator.launch_guard`, which gates real actions).

## The 7 strategy presets

| Strategy | Status | Notes |
|---|---|---|
| `own_ecommerce_low_cost` | reachable | Hostinger + WooCommerce + Mercado Pago/Stripe MX — the default |
| `client_ecommerce_low_cost` | reachable | Same stack, client-facing |
| `client_ecommerce_shopify_premium` | reachable | Shopify, only when `margin_sensitivity != "low_cost_validation"` |
| `marketos_owned_stack` | reachable | Medusa, self-hosted |
| `high_ticket_lead_gen_low_cost` | **deferred (Phase 2)** | needs a CRM/Conversation provider not yet modeled |
| `high_ticket_lead_gen_gohighlevel_fast` | **deferred (Phase 2)** | needs a CRM provider not yet modeled |
| `agency_white_label_fast` | **deferred (Phase 2)** | needs CRM/Conversation providers not yet modeled |

Deferred strategies return an explicit `status="not_yet_supported"` result
with a `warnings` entry naming what's missing — never a raised exception,
never a silently wrong recommendation.

## Hard rules (`backend/stack_planner/recommendations.py`)

| Rule | Function | Behavior |
|---|---|---|
| No GoHighLevel below its revenue threshold | `gohighlevel_allowed` | blocked with reason until `expected_monthly_revenue_usd` clears the cheapest GoHighLevel plan's `min_monthly_revenue_usd` |
| No Shopify when WooCommerce is sufficient and margin-sensitive | `shopify_allowed_over_woo` | blocked when `margin_sensitivity == "low_cost_validation"` |
| n8n never for a white-labeled client-facing product | `n8n_allowed` | blocked when `is_white_labeled_client_facing` is `True` — n8n stays internal-only per `docs/oss/LICENSE_MANIFEST.yml` |
| Postiz never without legal approval | `postiz_allowed` | blocked unless `postiz_legal_approval=True` |

Blocked providers are still returned in `automation_recommendations` with
`blocked=True` and a `blocked_reason` — never silently omitted.

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

- `python -m marketos.cli stack recommend ...` — lighter, non-billable
  utility, no `CommercialRunEnvelope`/audit log.
- `python -m marketos.cli services profit-stack-advisor ...` /
  `POST /api/services/profit-stack-advisor` — the sellable, audited variant
  (see `docs/SERVICE_MODULES.md`'s Profit Stack Advisor section).
