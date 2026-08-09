# Shopify vs. Hostinger+WooCommerce

The decision logic `backend.stack_planner.recommendations.shopify_allowed_over_woo`
encodes, laid out as a comparison table and decision tree. For the
Mexico-specific numeric walkthrough (with Mercado Pago/Stripe MX payment
fees), see `docs/LOW_COST_MEXICO_STACK.md`. This doc is the general
decision framework the Stack Planner's `client_ecommerce_shopify_premium`
vs. `own_ecommerce_low_cost`/`client_ecommerce_low_cost` strategies apply.

## Side-by-side

| | Hostinger + WooCommerce | Shopify |
|---|---|---|
| Fixed monthly cost | ~$3.99–8.99/mo (hosting only; WooCommerce plugin is free) | $39–399/mo depending on plan |
| Payment processing | Whatever processor you choose (Stripe MX, Mercado Pago MX, etc.) | Shopify Payments, 2.7–2.9% + $0.30 (lower on higher tiers) |
| Checkout | Self-hosted, fully customizable | Shopify's hosted checkout — polished, less customizable pre-Plus |
| App ecosystem | WordPress/WooCommerce plugin ecosystem | Shopify App Store — larger, more commerce-specific |
| Data ownership | Full — your database, your host | Shopify-hosted; exportable but not self-owned |
| Setup complexity | Higher (WordPress + WooCommerce + hosting + a payment plugin) | Lower (managed platform, guided setup) |
| Scaling ceiling | Bounded by your hosting tier and your own optimization | Shopify manages infrastructure scaling for you |

## Decision tree (matches `shopify_allowed_over_woo` + `build_commerce_recommendation`)

```
Is margin_sensitivity == "low_cost_validation"?
  YES -> WooCommerce (Shopify blocked; not yet worth the fixed cost)
  NO  -> Is this an existing Shopify store, or does the business need
         Shopify's app ecosystem / hosted checkout specifically?
           YES -> Shopify
           NO  -> Does expected_monthly_revenue_usd clear Shopify Advanced's
                  $10,000/mo threshold (from the Provider Registry catalog)?
                    YES -> Shopify (Advanced plan)
                    NO  -> Shopify (Basic/Grow) if margin_sensitivity is
                           "premium_brand", else WooCommerce
```

## When WooCommerce is the right call

- Pre-revenue or early-validation businesses (`margin_sensitivity="low_cost_validation"`)
  where a $39+/mo fixed cost isn't justified yet.
- Margin-sensitive dropshipping/low-ticket products where every dollar of
  fixed cost directly erodes `calculate_margin`'s net margin.
- Businesses that want full data ownership and no vendor lock-in on their
  commerce data.

## When Shopify is the right call

- An existing Shopify store — migration cost/risk outweighs the fixed-cost
  savings.
- A brand that needs Shopify's checkout polish or app ecosystem
  (subscriptions, complex inventory, POS integration) specifically.
- Revenue has cleared a tier where the higher fixed cost is a rounding
  error against margin (`margin_sensitivity="premium_brand"` or revenue
  clears a plan's `min_monthly_revenue_usd`).

## Try it

```
python -m marketos.cli stack recommend --business-model client_ecommerce_shopify_premium \
  --margin-sensitivity low_cost_validation --json   # -> WooCommerce, Shopify blocked

python -m marketos.cli stack recommend --business-model client_ecommerce_shopify_premium \
  --margin-sensitivity premium_brand --json          # -> Shopify
```

See `docs/STACK_PLANNER.md` for the full strategy/rule reference and
`docs/PROVIDER_REGISTRY.md` for the underlying catalog data.
