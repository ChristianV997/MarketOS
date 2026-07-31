# Provider Registry (`backend/providers`)

A static, in-memory catalog of third-party commerce/payment/hosting/
automation providers and their documented cost structure — the data
`backend/costs` and `backend/stack_planner` compare and recommend over. Not
a live pricing API and not a credential store: no dollar figure here is
fetched at runtime, and no secret ever lives in this module.

## Schema (`backend/providers/schemas.py`)

- **`Provider`** — `provider_id`, `name`, `category` (one of
  `hosting`, `commerce_platform`, `headless_commerce`, `payment_processor`,
  `crm`, `conversation_inbox`, `workflow_automation`, `marketing_automation`,
  `social_publishing`), `capabilities` (tuple of strings), `integration_status`
  (`catalog_only` | `adapter_available`), `plans`, `risk`, `license`,
  `oss_inventory_ref` (cross-reference into `docs/oss/INVENTORY.yml` when
  applicable), `notes`.
- **`ProviderPlan`** — `plan_id`, `display_name`, `cost_components`,
  `min_monthly_revenue_usd` (the threshold a Stack Planner rule reads to
  decide whether this plan is affordable for a given business), `notes`.
- **`ProviderCostComponent`** — `kind` (`fixed_monthly` | `payment_pct` |
  `payment_fixed` | `per_order` | `usage_overage`), `amount`, `unit`, `notes`.
- **`ProviderRisk`** — `level`, `reasons`, `requires_legal_approval` (the
  Postiz/AGPL gate), `internal_only` (the n8n gate).
- **`ProviderRecommendation`** — what `backend.stack_planner` actually
  returns per provider: `selected_plan_id`, `monthly_cost_estimate`,
  `reasons`, `warnings`, `blocked`, `blocked_reason`.

## Registry (`backend/providers/registry.py`)

```python
from backend.providers import provider_registry

provider_registry.get("woocommerce")          # -> Provider, raises KeyError if unknown
provider_registry.list()                       # -> tuple[Provider, ...]
provider_registry.by_category("payment_processor")
```

`ProviderRegistry.register()` raises `ValueError` on a duplicate
`provider_id` — a duplicate is always a bug, never an intentional override.
This mirrors the one existing registry precedent in the repo,
`backend.adapters.research.registry.ResearchAdapterRegistry`.

`integration_status_for(provider_id, workspace)` composes
`backend.workspaces.credential_scope.scope_for` to report whether a
provider is actually usable *right now* for a given workspace (credentials
configured, dry-run state) — separate from the static catalog data above.

## Adding a new provider

1. Search first — grep the provider name across `.py`/`.yml`/`.md` to
   confirm it's genuinely new (see `docs/COST_AWARE_INTEGRATION_AUDIT.md`'s
   own audit for the discipline this follows).
2. Add a `Provider(...)` entry to `backend/providers/provider_catalog.py`,
   registered via `provider_registry.register(...)` in `_register_all()`.
3. If the provider is a real OSS candidate, add a matching entry to
   `docs/oss/INVENTORY.yml` + `docs/oss/LICENSE_MANIFEST.yml` +
   `THIRD_PARTY_NOTICES.md` (same license value in all three — enforced by
   `tests/test_oss_governance_sync.py`) and set `oss_inventory_ref`.
4. If the provider needs a live adapter (not just catalog data), see
   `docs/STACK_PLANNER.md`'s adapter section for the existing convention
   (`backend/contracts/adapters.py` Protocol → `backend/integrations/*`
   implementation → `backend/workspaces/credential_scope.py` wiring).

## Current catalog (Phase 1)

`hostinger`, `woocommerce`, `medusa`, `shopify`, `stripe_mx`,
`mercado_pago_mx`, `chatwoot`, `n8n`, `mautic`, `activepieces`,
`gohighlevel`, `postiz` — see `backend/providers/provider_catalog.py` for
exact plans/pricing.
