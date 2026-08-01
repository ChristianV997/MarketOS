# Cost-aware integration audit

Why this exists, what already existed before this pass, what's new, what's
deliberately reused instead of rebuilt, and what's explicitly deferred.
Written before — and kept accurate after — building `backend/providers`,
`backend/costs`, `backend/stack_planner`, `services/profit_stack_advisor`,
and the WooCommerce/Stripe MX/Mercado Pago MX adapters.

## 1. Existing capabilities kept native (not touched, not duplicated)

MarketOS already owns the parts of this problem that are genuinely hard to
get right and genuinely differentiated:

- **Margin/cost math** — `backend/validation/margin_calculator.py`
  (`calculate_margin`, `calculate_margin_geo`, `calculate_ltv_adjusted_margin`,
  `suggest_retail_price`).
- **Break-even/ROAS** — `services/unit_economics/break_even.py`.
- **Contribution-profit truth** — `services/ecommerce_operator/contribution_profit.py`,
  `backend/metrics/attribution.py::reconcile_revenue` (scales down only,
  never inflates platform self-reports).
- **CAC/LTV** — `backend/economics/ltv.py`.
- **Event-sourced commerce ledger** — `backend/ledger/` (see
  `docs/COMMERCE_LEDGER.md`).
- **Dry-run/live-mode/credential gating** — `backend/workspaces/{client_workspace,
  credential_scope,live_mode_checklist}.py`.
- **The existing ports/adapter system** — `backend/contracts/adapters.py`'s
  Protocols (`CommerceProvider`, `ProductResearchProvider`, `SupplierProvider`,
  `BrowserWorkflowProvider`, `ContentPublisher`, `WorkflowAutomationProvider`,
  `AgentProvider`, and now `PaymentProvider`).

## 2. Existing integrations reused, not duplicated

- **Commerce**: the new WooCommerce adapter (`backend/integrations/woocommerce/`)
  implements the *existing* `CommerceProvider` Protocol — there is no new
  "CommercePort". Medusa (`backend/integrations/medusa.py`) is unchanged.
- **Payment**: a new `PaymentProvider` Protocol was added to
  `backend/contracts/adapters.py` (a genuine gap — only a bare credential key
  existed before), implemented by `backend/integrations/stripe_mx.py` and
  `backend/integrations/mercado_pago_mx.py`. This is fee-*estimation* and
  read-only payment/refund access — distinct from
  `connectors/stripe_connector.py::get_revenue`'s ground-truth revenue-
  reconciliation job, which is untouched.
- **Workflow automation**: `n8n` (`backend/integrations/n8n.py`,
  `WorkflowAutomationProvider`) is reused as-is for internal ops; it remains
  internal-only per existing governance (`docs/oss/LICENSE_MANIFEST.yml`).

## 3. Existing OSS sidecars + status

See `docs/oss/INVENTORY.yml` / `docs/oss/LICENSE_MANIFEST.yml` for the
canonical record. Status across both Phase 1 and Phase 2:

| Candidate | Status before Phase 1 | Status after Phase 2 |
|---|---|---|
| woocommerce | (absent) | `legal_review_required` — adapter built and tested, same precedent as Postiz: GPL-3.0 is a restricted license under `scripts/check_oss_policy.py`'s blanket policy, so formal legal review is recorded as required before a real commercial rollout, even though the adapter only makes independent API calls to a merchant-operated WooCommerce instance (no MarketOS-vendored/distributed GPL source, no derivative work) |
| mautic | (absent) | `legal_review_required` — MarketingAutomationProvider adapter built and tested; GPL-3.0-or-later is copyleft, treated with the same legal-review precedent as GPL-3.0/AGPL-3.0 even though the exact-string policy checker doesn't currently match "-or-later" |
| activepieces | (absent) | `selected` — CustomerAutomationProvider adapter built and tested; MIT, no legal-review gate needed |
| chatwoot | `deferred` | `selected` — ConversationProvider adapter built and tested (Phase 1 advanced it to `candidate_for_conversation_sidecar`, Phase 2 to `selected` once the adapter shipped); MIT, no legal-review gate needed |
| posthog | `selected` (frontend-only) | `selected`, unchanged status — Phase 2 added a second, server-side consumption (backend/integrations/posthog_backend.py, AnalyticsProvider) against the same PostHog Cloud project, noted in the existing entry rather than duplicated |
| twenty-crm | `deferred` | unchanged — AGPL-3.0, left untouched by explicit prior user decision; no CRMProvider adapter built (see §4) |
| n8n | `internal_only` | unchanged |
| postiz | `legal_review_required` | unchanged |

## 4. Missing integration ports — Phase 1 gaps, now closed in Phase 2

Phase 1 confirmed via repo-wide search: **no** Protocol existed for
Hosting, Analytics (backend), CRM, Conversation/Inbox, or Marketing
Automation, and closed the Payment gap only (the highest-value one for the
MX commerce/payment decision this spec's own headline example calls for),
deferring the rest.

Phase 2 closed four of the remaining five: `ConversationProvider`
(Chatwoot), `AnalyticsProvider` (PostHog backend), `MarketingAutomationProvider`
(Mautic), `CustomerAutomationProvider` (Activepieces — a new Protocol
distinct from the internal-only `WorkflowAutomationProvider`/n8n), and
`HostingProvider` (Hostinger, read-only). See `docs/INTEGRATION_PORTS.md`
for the full Protocol/adapter table.

**`CRMProvider` remains a genuine, deliberate gap.** The Protocol exists
(`backend/contracts/adapters.py::CRMProvider`), but no concrete adapter was
built: Twenty, the catalog's one low-cost CRM candidate, is AGPL-3.0 and
was left deferred pending legal review by an explicit prior user decision
in an earlier session — reversing that without the user re-confirming it
would be out of scope for this pass. The Stack Planner's lead-gen
strategies (§9) report this gap honestly (`crm_provider_recommendation.blocked=True`
with an explanatory reason) rather than recommending Twenty anyway or
fabricating a substitute; GoHighLevel (proprietary) fills the CRM need for
strategies where its revenue threshold is cleared.

## 5. Where the repo already beats external SaaS

- Contribution-profit reconciliation, break-even/ROAS derivation, and the
  event-sourced ledger have no equivalent in any of the evaluated providers
  — they're MarketOS's actual differentiation, and nothing here delegates them.
- The dry-run/live-mode/credential-gating system is more rigorous than most
  of the evaluated SaaS tools' own safety rails.

## 6. Where external SaaS/OSS should be used instead of rebuilt

- Commerce checkout/cart/fulfillment (WooCommerce, Shopify, Medusa) — do not
  reimplement a storefront.
- Payment processing (Stripe, Mercado Pago) — do not reimplement PCI-scope
  payment handling.
- Hosting (Hostinger) — do not reimplement infrastructure provisioning.

## 7. Duplicate/overlapping modules avoided

- No new `backend/ports/` directory — new Protocols extend
  `backend/contracts/adapters.py`, the one existing ports system.
- No new margin/fee formula — `backend/costs` composes
  `backend.validation.margin_calculator` via three small additive overrides
  (`payment_fee_pct`, `payment_fee_fixed`, `platform_monthly_fee`, all
  defaulting to `None` — byte-identical to prior behavior when omitted).
- No duplicate OSS inventory entries — `chatwoot`/`mautic`/`activepieces`/
  `posthog` were updated in place (status/notice changes), not re-added;
  `twenty` is a genuinely new `backend/providers` catalog entry but reuses
  the existing `twenty-crm` OSS inventory record via `oss_inventory_ref`
  rather than creating a second one.
- No sibling Protocol for Activepieces alongside `WorkflowAutomationProvider` —
  a new, distinctly-scoped `CustomerAutomationProvider` was added instead
  (see `docs/INTEGRATION_PORTS.md`), preserving `WorkflowAutomationProvider`'s
  internal-only guarantee rather than weakening it.

## 8. Cost/compatibility risks

- WooCommerce's `legal_review_required` governance status (see §3) is a
  compliance record, not a Stack Planner gate — unlike Postiz, the Stack
  Planner still recommends WooCommerce by default, since the adapter is an
  independent REST API client against a merchant-operated instance (no
  vendored/distributed GPL source). Confirm this reasoning holds before any
  real commercial rollout; it is not a substitute for actual legal sign-off.

- Provider catalog dollar figures (`backend/providers/provider_catalog.py`)
  are documented, conservative estimates, not live price lookups — they will
  drift from real pricing over time and should be periodically re-verified.
- WooCommerce has no server-side cart resource and no native fulfillment
  sub-resource — the adapter's `create_cart`/`fulfill_order` are documented,
  best-effort mappings, not a 1:1 match with Medusa's shape.
- Stripe MX / Mercado Pago MX adapters estimate fees independently of
  `connectors/stripe_connector.py`; if the two ever need to reconcile against
  each other, that reconciliation doesn't exist yet.

## 9. Recommended implementation sequence

1. **Done, Phase 1**: Provider Registry, Cost Engine, Stack Planner (4 of 7
   presets reachable), WooCommerce + Stripe MX + Mercado Pago MX adapters,
   Profit Stack Advisor service, CLI/API/docs/tests, OSS governance updates.
2. **Done, Phase 2**: `CRMProvider` (Protocol only — see §4), `ConversationProvider`,
   `AnalyticsProvider` (backend), `MarketingAutomationProvider`, `CustomerAutomationProvider`,
   `HostingProvider` Protocols; adapters for Chatwoot, Mautic, Activepieces,
   PostHog (backend), Hostinger (Twenty deliberately excluded — see §4); all
   3 remaining Stack Planner strategies (`high_ticket_lead_gen_low_cost`
   recommends Chatwoot+Mautic and reports the CRM gap honestly;
   `high_ticket_lead_gen_gohighlevel_fast`/`agency_white_label_fast`
   recommend GoHighLevel above its revenue threshold); `docs/SAAS_MARGIN_POLICY.md`,
   `docs/SHOPIFY_VS_HOSTINGER_WOOCOMMERCE.md`, `docs/INTEGRATION_PORTS.md`;
   `POST /api/stack/recommend`; the workspace-isolation test + frontend
   dashboard coverage for `profit_stack_advisor` (see `docs/SERVICE_MODULES.md`'s
   "SaaS-lite readiness" section).
3. **Later (not started)**: an actual Twenty CRM adapter, if/when a
   dedicated legal review of its AGPL-3.0 license is completed and the user
   explicitly revisits the deferral; a real hosting-provisioning workflow
   (today's `HostingProvider` is read-only status/plan-usage only, by
   design — MarketOS does not provision infrastructure).
