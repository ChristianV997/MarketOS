# The low-cost Mexico commerce stack

The default recommendation `backend.stack_planner` produces for a
cost-sensitive Mexican commerce business, and why — a concrete walkthrough
of `own_ecommerce_low_cost` using the actual numbers in
`backend/providers/provider_catalog.py` at time of writing (documented
estimates, env-overridable — see `docs/PROVIDER_REGISTRY.md`).

## The stack

| Layer | Provider | Fixed cost | Notes |
|---|---|---|---|
| Hosting | Hostinger (Business Web Hosting) | ~$3.99/mo | cheapest tier that runs WordPress/WooCommerce |
| Commerce | WooCommerce | $0/mo | free plugin; the adapter (`backend/integrations/woocommerce/`) implements the existing `CommerceProvider` Protocol |
| Payment | Mercado Pago (MX) | 3.49% + $0 MXN/txn | regionally preferred in MX; marginally lower blended fee than Stripe MX (3.6% + $3 MXN) in the current catalog |

Total fixed cost: **~$3.99/mo** before payment processing — versus Shopify
Basic's $39/mo fixed + 2.9%+$0.30 payment fee, which is why the Stack
Planner defaults here whenever `margin_sensitivity` isn't `"premium_brand"`.

## Why not Shopify by default

Shopify is fully supported (`client_ecommerce_shopify_premium`) and
recommended when:
- an existing Shopify store or its app ecosystem/checkout experience is a
  real requirement, or
- `margin_sensitivity="premium_brand"` — the brand experience justifies the
  higher fixed cost, or
- expected revenue clears Shopify Advanced's own `min_monthly_revenue_usd`
  threshold ($10,000/mo).

Otherwise `shopify_allowed_over_woo` blocks it: WooCommerce is sufficient
and cheaper, and recommending a $39+/mo platform for a validation-stage or
margin-sensitive business would cost the client money without adding value
— exactly the failure mode this whole effort exists to prevent.

## Why not GoHighLevel / Postiz / n8n by default

- **GoHighLevel** ($97+/mo) is blocked until `expected_monthly_revenue_usd`
  clears its cheapest plan's threshold ($3,000/mo) — see
  `gohighlevel_allowed` in `docs/STACK_PLANNER.md`.
- **Postiz** (AGPL-3.0) is blocked without an explicit
  `postiz_legal_approval=True` flag.
- **n8n** is blocked for any white-labeled, client-facing product — it stays
  internal-only per existing OSS governance
  (`docs/oss/LICENSE_MANIFEST.yml`).

## Try it

```
python -m marketos.cli stack recommend \
  --business-model own_ecommerce --target-geo MX \
  --expected-monthly-revenue 5000 --margin-sensitivity low_cost_validation \
  --supplier-cost 10 --retail-price 35 --json
```

or the sellable, audited variant:

```
python -m marketos.cli services profit-stack-advisor \
  --business-name "Own Store" --workspace own-store \
  --business-model own_ecommerce --expected-monthly-revenue 5000 \
  --supplier-cost 10 --retail-price 35 --json
```

See `docs/STACK_PLANNER.md` for the full rule table and preset list.
