# Commerce ledger

An event-sourced record of real commerce facts (orders, payments, refunds,
supplier costs, ad spend, attribution claims), and the derived numbers
(CAC, contribution profit, cash conversion cycle, profit-per-{order,
product, channel}) computed from replaying them. Defined in
`backend/ledger/`.

## Why it exists

Before this module, every profit/CAC calculation in MarketOS
(`backend.validation.margin_calculator.calculate_margin`,
`backend.metrics.attribution.reconcile_revenue`, and the `services.*`
wrappers around them) took **ad-hoc scalar inputs** — a revenue number, a
spend number — supplied by the caller. That's correct and sufficient when
you already have the numbers in hand (a one-off unit-economics check), but
there was no durable, replayable record of the underlying events those
numbers should come from. `backend/ledger/` is that record.

## Events, not a new log

`backend.ledger.events` defines nine event types — `OrderCreated`,
`PaymentCaptured`, `OrderCanceled`, `RefundIssued`, `ChargebackOpened`,
`SupplierCostObserved`, `FulfillmentCompleted`, `AdSpendObserved`,
`AttributionClaimObserved` — each a thin, never-raising wrapper around
`backend.orchestration.event_store.event_store.append()`, the same
durable JSONL log every dry-run/shadow gate in this repo already writes
to. There is no second event-store file: querying is done via
`event_store.events_of_type(event_type)`, filtered by each event's
`workspace_id`.

```python
from backend.ledger.events import record_order_created, record_payment_captured

record_order_created(ws.workspace_id, "order-123", product_name="Widget",
                      channel="meta", revenue=40.0)
record_payment_captured(ws.workspace_id, "order-123", amount=40.0)
```

## Projections: replay, don't duplicate

`backend.ledger.projections.compute_projection(workspace_id) ->
LedgerSnapshot` replays every event for that workspace into:

- `recognized_revenue`, `cash_collected`, `gross_profit`, `contribution_profit`, `contribution_margin`
- `cac_blended`, `cac_by_channel`
- `profit_per_order`, `profit_per_product`, `profit_per_channel`, `revenue_by_channel`
- `cash_conversion_cycle_days` — a **deliberately simplified proxy**
  (average days between order creation and payment capture), not the
  full DIO+DSO-DPO formula, since this ledger doesn't track
  inventory-holding or accounts-payable events. Documented here, not
  silently overstated.

Never raises: an empty or missing event history for a workspace simply
yields an all-zero `LedgerSnapshot`.

## Composition with existing calculators — additive, not a rewrite

`backend/ledger/` does not reimplement margin or attribution math.
Instead, `services.unit_economics.analyzer.from_ledger()` and
`services.ecommerce_operator.contribution_profit.from_ledger()` are new,
additive entry points alongside each module's existing direct-input
function:

```python
from services.unit_economics.analyzer import from_ledger

result, envelope = from_ledger(
    "Widget", workspace=ws, supplier_cost=10.0, retail_price=40.0,
)
```

`from_ledger` derives `monthly_ad_spend`/`expected_monthly_revenue` from
`compute_projection(workspace.workspace_id)` and passes them into the
same `backend.validation.margin_calculator.calculate_margin` every other
call path already uses — falling back to `calculate_margin`'s own
defaults (`monthly_ad_spend=500.0`, `expected_monthly_revenue=5000.0`)
when the ledger has no recorded events yet, so an empty ledger degrades
gracefully instead of producing a zero-CAC/zero-revenue nonsense result.

Similarly, `services.ecommerce_operator.contribution_profit.from_ledger(envelope)`
derives `campaign_revenue`, `ground_truth_revenue`, `actual_spend`,
`actual_orders`, `refunds`, and `supplier_costs` from the same snapshot
and passes them straight into the existing
`reconcile_contribution_profit()` — which still calls
`backend.metrics.attribution.reconcile_revenue` exactly as before.

Existing callers of `run_unit_economics()` / `reconcile_contribution_profit()`
with real numbers already in hand are completely unaffected — both
functions keep their original signatures.

## What this deliberately does not do

- No new persistence primitive: projections use
  `backend.core.persistence.state_path()`/`save_json_atomic()` for any
  cached snapshot, the same idiom `PatternStore`/`CalibrationStore`/
  `WorkspaceRegistry` already use — no separate database.
- No canonical bounded-context restructuring — this ledger lives under
  `backend/ledger/`, not a new `commerce/` or `orders/` top-level package;
  see `docs/MARKETOS_MODULAR_ARCHITECTURE.md`'s directory map.
- No real payment/order integration wiring yet — nothing in
  `backend/integrations/*` calls `backend.ledger.events` automatically.
  Recording real webhook-sourced events (Shopify order/payment webhooks,
  TikTok/Meta spend ingestion) into this ledger is future, explicitly
  scoped work, not part of this phase.
- No changes to the two-audit-logs-on-purpose fork
  (`backend/events/log.py` vs `backend/orchestration/event_store.py`) —
  still out of scope, per `docs/COMMERCIAL_RUN_ENVELOPE.md`.
