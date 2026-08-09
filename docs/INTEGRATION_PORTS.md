# Integration ports (`backend/contracts/adapters.py`)

The complete list of vendor-neutral Protocols MarketOS adapters implement,
in one place, with which concrete adapters satisfy each and which are still
gaps. All Protocols live in `backend/contracts/adapters.py` — there is no
separate `backend/ports/` directory; a second parallel ports system would
itself be the kind of duplication this effort has repeatedly avoided (see
`docs/COST_AWARE_INTEGRATION_AUDIT.md`).

Every Protocol requires `health() -> AdapterHealth`. Mutating methods take
a `SidecarContext` (workspace/run/artifact lineage, `dry_run`,
`approval_state`, `idempotency_key`) and follow the same gate sequence:
`dry_run=True` → stub response, no side effect; `dry_run=False` requires
`approval_state == "approved"` and `context.require_live_idempotency()`.

| Protocol | Scope | Concrete adapter(s) | Status |
|---|---|---|---|
| `CommerceProvider` | catalog/inventory/cart/order/fulfillment/refund | `medusa.py`, `integrations/woocommerce/` | live |
| `ProductResearchProvider` | product/trend discovery | `adapters/research/crawl4ai.py` and others | live |
| `SupplierProvider` | supplier offer lookup | `medusa.py` (dual-role) | live |
| `BrowserWorkflowProvider` | permissioned browser automation | `browser_use_worker.py` | live |
| `ContentPublisher` | social publishing | `postiz.py` | live (legal-review-required, AGPL-3.0) |
| `WorkflowAutomationProvider` | **internal-only** operational automation (notifications, CRM sync, exports) | `n8n.py` | live (internal-only per governance) |
| `PaymentProvider` | fee estimation + read-only payment/refund access | `stripe_mx.py`, `mercado_pago_mx.py` | live |
| `AgentProvider` | typed-agent creation | `agents/pydantic_boundary.py` | live |
| `CRMProvider` | contacts/opportunities/pipeline stage/activity | *(none)* | **gap** — Twenty (AGPL-3.0) deferred pending legal review; GoHighLevel (proprietary) fills the CRM need via the Stack Planner's automation recommendations instead of this Protocol |
| `ConversationProvider` | inbox/support conversation, draft-only sends | `chatwoot.py` | live |
| `AnalyticsProvider` | backend/server-side event capture + query | `posthog_backend.py` | live (distinct from the frontend-only posthog-js client) |
| `MarketingAutomationProvider` | email/segment/campaign automation | `mautic.py` | live (GPL-3.0-or-later, treated with the same legal-review precedent as GPL-3.0/AGPL-3.0) |
| `CustomerAutomationProvider` | customer-facing/product no-code workflow runtime | `activepieces.py` | live — **distinct from** `WorkflowAutomationProvider` (n8n), which stays internal-only |
| `HostingProvider` | read-only hosting status/plan-usage | `hostinger.py` | live (read-only; MarketOS does not provision infrastructure) |

## Why `CustomerAutomationProvider` is not `WorkflowAutomationProvider`

`WorkflowAutomationProvider`'s own docstring scopes it to MarketOS's
internal operations ("not a product runtime"). Activepieces is a
customer-facing, product-embeddable automation tool — folding it into the
internal-only Protocol would either weaken that Protocol's documented
guarantee or require every internal n8n call site to re-check a "is this
internal or customer-facing" flag that doesn't otherwise need to exist.
A separate Protocol keeps both guarantees intact and legible.

## Why `PaymentProvider` is distinct from `connectors.stripe_connector`

`connectors/stripe_connector.py::get_revenue()` is the ground-truth
revenue-reconciliation connector `backend.metrics.attribution` composes.
`PaymentProvider` implementations never reconcile recognized revenue — they
only estimate processing fees (always available, even with zero
credentials) and read payment/refund records for Stack Planner cost
comparisons. Keeping them separate avoids two very different
responsibilities (financial-reporting ground truth vs. stack-cost
estimation) sharing one interface.

## Adding a new port

1. Confirm the capability genuinely has no existing Protocol (grep
   `backend/contracts/adapters.py` first).
2. Add the Protocol to `backend/contracts/adapters.py`, matching the
   existing convention exactly (frozen dataclasses, `health()` required,
   `SidecarContext` only on mutating methods).
3. Add a concrete adapter under `backend/integrations/` following the
   `dry_run` → `approval_state=="approved"` → `require_live_idempotency()`
   gate sequence used by every existing adapter.
4. Wire credentials into `backend/config.py::_SERVICE_CREDENTIALS` and
   `backend/workspaces/credential_scope.py::_INTEGRATION_TO_CONFIG_SERVICE`.
5. Register the provider's catalog data in
   `backend/providers/provider_catalog.py` and flip its
   `integration_status` to `adapter_available`.
6. Extend `scripts/validate_oss_runtime.py`'s `providers`/`dry_run_boundaries`
   and `docs/oss/{INVENTORY.yml,LICENSE_MANIFEST.yml}` +
   `THIRD_PARTY_NOTICES.md` if the provider is a real OSS candidate —
   `tests/test_oss_governance_sync.py` enforces the three files stay
   consistent.
