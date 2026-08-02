# Digital product workflow

The end-to-end internal workflow for turning a MarketOS artifact (a
product-research audit, a unit-economics diagnostic, a creative-growth
plan, or your own accumulated expertise) into a sellable digital product,
using `services.digital_products`. Every step here is real code you can
run today.

## Workflow

1. **Select an artifact from MarketOS results.** Any prior
   `CommercialRunEnvelope`'s output works — e.g. a `ProductAuditResult`
   that found a strong validated niche, or a `CreativeGrowthPlan` full of
   proven hooks/angles worth teaching as a playbook.
   ```python
   from backend.experiments.registry import get_experiment_registry
   from backend.workspaces.artifact_store import ArtifactStore

   registry = get_experiment_registry()
   store = ArtifactStore()
   past_experiments = registry.for_workspace(ws.workspace_id)
   source_artifact = store.load(ws.workspace_id, past_experiments[0].experiment_id, "result.json")
   ```

2. **Convert to a product type**: `create_digital_offer` supports
   `template`, `playbook`, `course`, `cohort`, `ebook`, `paid_report`,
   `prompt_pack`, `calculator`, `dashboard_access`, `mentorship`
   (`services.digital_products.schemas.PRODUCT_TYPES`).

3. **Define the target customer** (part of the same call):
   ```python
   from services.digital_products import create_digital_offer
   offer = create_digital_offer(
       "Product Validation Playbook", product_type="playbook",
       target_customer="aspiring dropshippers",
       transformation_promised="validate a product idea in under a day instead of a week",
       price=497.0,
   )
   ```

4. **Build the offer** — step 3 already produced it; `offer.to_dict()` is
   the structured record.

5. **Build the funnel**:
   ```python
   from services.digital_products import build_funnel_plan
   funnel = build_funnel_plan(offer)  # lead magnet + funnel steps + sales-page structure, type-specific
   ```

6. **Generate the content plan** (reuses `services.creative_growth`'s
   angle generator rather than a second one):
   ```python
   from services.digital_products import generate_content_plan
   content_plan = generate_content_plan(offer)
   ```

7. **Validate with a low-budget/organic test** — before building the full
   product, get an honest traffic/conversion estimate:
   ```python
   from services.digital_products import validate_digital_product
   validation = validate_digital_product(
       offer, target_buyers=10, has_existing_audience=False,
   )
   print(validation.verdict, validation.reasoning)  # unsafe | fragile | viable | strong
   ```
   Only proceed to a paid test once `verdict` is `viable` or `strong` —
   `build_launch_checklist` encodes this explicitly as one of its items.

8. **Track leads, purchases, CAC, conversion rate** — not automated by
   this module (there's no payment/analytics integration here); the
   checklist and `metrics_to_track` list name exactly what to instrument:
   visitors, opt-in rate, checkout conversion rate, refund rate, CAC.

9. **Decide kill/iterate/scale** — `decision_criteria` (part of the full
   plan) states the explicit thresholds:
   ```python
   from services.digital_products import build_digital_product_plan, render_digital_product_markdown

   plan, envelope = build_digital_product_plan(
       "Product Validation Playbook", product_type="playbook",
       target_customer="aspiring dropshippers",
       transformation_promised="validate a product idea in under a day instead of a week",
       price=497.0, target_buyers=10, workspace=ws,
   )
   print(render_digital_product_markdown(plan))
   ```
   `build_digital_product_plan` runs steps 2-9 above in one call, tied to
   a `CommercialRunEnvelope` and saved to the workspace's `ArtifactStore` —
   the individual functions above exist so you can also run any single
   step standalone.

## What this workflow deliberately does not do

- It does not track real leads/purchases itself — step 8's numbers come
  from wherever you actually sell (Stripe, Gumroad, a course platform);
  this module only tells you *what* to track and *what verdict* those
  numbers should produce.
- `validate_digital_product`'s traffic/conversion estimate uses explicitly
  labeled, conservative assumptions (1.5% cold-traffic / 5% warm-audience
  conversion) — override `assumed_conversion_rate_pct` with your own real
  funnel data once you have it; these are starting assumptions, not
  measured facts.
- No payment processing, no course-hosting integration, no email-sequence
  sending — `build_launch_checklist` names these as manual/external setup
  steps rather than pretending they're automated.
