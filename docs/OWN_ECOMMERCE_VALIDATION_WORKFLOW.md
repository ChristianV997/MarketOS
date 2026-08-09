# Own e-commerce validation workflow

The end-to-end internal workflow for validating one of your own products,
using `services.product_research`, `services.unit_economics`, and
`services.ecommerce_operator` together. Every step here is real code you
can run today — this isn't aspirational.

## Workflow

1. **Create your own-store workspace** (once):
   ```python
   from backend.workspaces.client_workspace import ClientWorkspace
   from backend.workspaces.registry import get_workspace_registry

   ws = ClientWorkspace(
       name="own-store", workspace_type="internal", mode="internal_own_store",
       budget_ceiling_monthly=1000.0, budget_ceiling_per_experiment=100.0,
   )
   get_workspace_registry().register(ws)
   ```

2. **Run a product/category audit**:
   ```python
   from services.product_research import run_product_audit
   audit_result, _ = run_product_audit("Posture Corrector", category="wellness", workspace=ws)
   ```
   Or from the terminal: `python -m marketos.cli services product-audit --product "Posture Corrector" --category wellness --workspace own-store`

3. **Run the unit economics diagnostic** (supplier/margin validation):
   ```python
   from services.unit_economics import run_unit_economics
   econ_result, _ = run_unit_economics(
       "Posture Corrector", supplier_cost=12.0, retail_price=45.0, shipping_cost=3.0,
       category="wellness", workspace=ws,
   )
   ```
   `econ_result.verdict` (`profitable`/`breakeven`/`loss`) and `econ_result.break_even_cac`
   are your internal go/no-go gate before spending anything on creative or ads.

4. **Generate a creative plan** — deferred to a future phase
   (`services.creative_growth`, not built yet). For now, use the existing
   `core/creative/selection.py`/`core/content/patterns.py` hook/angle
   machinery directly if you need this step today.

5. **Create the commerce experiment**, carrying every prerequisite the
   launch guard checks for:
   ```python
   from services.ecommerce_operator import create_commerce_experiment
   experiment = create_commerce_experiment(
       "Posture Corrector",
       validation=audit_result.validation,
       unit_economics=econ_result.to_dict(),
       supplier_assumptions=audit_result.supplier,
       kill_criteria={"min_roas": 1.2, "min_contribution_margin": 0.10, "max_spend_before_kill": 50.0},
       attribution_method="shopify_ground_truth",
       workspace=ws,
   )
   ```

6. **Generate the landing/product page plan** — deferred; today, wire
   `backend.creation.store_builder.build_product()` directly from the
   validation verdict (already real, already wired) if you want to go this
   far manually.

7. **Run dry-run launch readiness** — this is the launch guard. It blocks
   if any prerequisite from step 5 is missing:
   ```python
   from services.ecommerce_operator import evaluate_launch_readiness
   readiness = evaluate_launch_readiness(experiment, workspace=ws)
   assert readiness.ready, readiness.blocked_reasons
   ```

8. **Manually approve a live test only when ready** — pass
   `live_action_requested=True` once you actually intend to spend real
   money. This additionally runs `backend.workspaces.live_mode_checklist`
   (credentials configured, workspace `live_mode_enabled`, budget
   ceilings) — see `docs/LIVE_MODE_SAFETY.md` (not yet written; see
   `backend/workspaces/live_mode_checklist.py`'s docstring in the
   meantime) for exactly what that checks:
   ```python
   readiness = evaluate_launch_readiness(
       experiment, workspace=ws, live_action_requested=True,
       integration="shopify", proposed_amount=50.0,
   )
   ```
   This function only *evaluates* readiness — it never itself calls
   `backend.integrations.tiktok_ads`/`meta_ads_client`/`store_builder`.
   Actually launching remains a separate, explicit call into those
   existing, already dry-run-gated modules.

9. **Import or manually enter ad spend/orders/supplier cost** once the
   test has run for a while (via whatever platform/Shopify data pull you
   already use — `backend.metrics.profitability.calculate_profitability()`
   is the existing source for this if you're running through the full
   orchestrator loop).

10. **Reconcile contribution profit** — this is where platform
    self-reported revenue gets scaled down to Shopify/Stripe ground truth
    before profit is computed, so double-counted attribution never inflates
    the decision:
    ```python
    from services.ecommerce_operator import reconcile_contribution_profit
    contribution = reconcile_contribution_profit(
        experiment,
        campaign_revenue={"tiktok_campaign_1": 500.0, "meta_campaign_1": 300.0},
        ground_truth_revenue=600.0,  # real Shopify/Stripe total for the window
        actual_spend=200.0, actual_orders=25, refunds=20.0,
        supplier_costs=150.0, payment_fees=30.0,
    )
    ```

11. **Decide kill/iterate/continue/scale** — driven by contribution
    profit and evidence volume, not ROAS alone:
    ```python
    from services.ecommerce_operator import make_kill_scale_decision
    roas = contribution.actual_revenue_reconciled / contribution.actual_spend
    decision = make_kill_scale_decision(experiment, contribution, roas=roas, proposed_scale_amount=100.0)
    print(decision.decision, "-", decision.decision_reason)
    ```
    `decision.decision` is one of: `kill`, `iterate_offer`, `iterate_creative`,
    `continue_test`, `scale_cautiously`, `scale_approved`, `blocked`. A
    `scale_approved`/`scale_cautiously` decision still doesn't spend
    anything itself — it tells you what the real spend-scaling call
    (`backend.integrations.tiktok_ads.scale_budget`/
    `meta_ads_client.update_ad_set_budget`, which already gate through
    `backend.risk.gate`) should do next.

12. **Convert results into content and digital products** — deferred to
    `services.digital_products` (not built yet).

## What this workflow deliberately does NOT do yet

- It does not itself call any live ad-platform or Shopify API — every step
  above produces a decision or a structured result; executing that
  decision against a real platform is a separate, already-existing,
  already dry-run-gated call (`backend/integrations/*`,
  `backend/creation/store_builder.py`).
- Steps 4, 6, and 12 (creative plan, landing page plan, digital-product
  conversion) reference future service modules that don't exist yet —
  called out explicitly rather than silently skipped.
- There is no automated end-to-end runner tying all 12 steps into one
  command; this is a manual (or your own script's) sequence today.
