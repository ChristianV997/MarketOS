# MarketOS service modules

The master reference for every sellable module built under `services/`.
Each wraps existing, already-real MarketOS infrastructure rather than
duplicating logic — see each module's own docstrings for exactly which
backend/core functions it reuses.

**Commercial status labels** (`services.status.STATUSES`), used consistently
across every module's top-level result's `status` field:

| Label | Meaning |
|---|---|
| `ready_for_dry_run` | Works today with no credentials/live data; safe fallback when a status check itself fails |
| `ready_for_internal_use` | Safe to run against your own workspace today, not yet positioned as a standalone paid deliverable |
| `ready_for_client_service` | The module's logic is real and complete — safe to sell as a delivered service today |
| `needs_live_data` | Output quality depends on real data (spend/orders/revenue) the module can't fetch itself — the caller must supply it |
| `needs_credentials` | A specific integration credential required for this workspace isn't configured |
| `future_saas` | Needs workspace/billing/auth infrastructure beyond what exists today to serve as self-serve SaaS |
| `future_dao` | Not applicable until `backend.dao_future`'s placeholder concepts become real (see `docs/DAO_FUTURE_ARCHITECTURE.md`) |

---

## 1. Product Research (`services.product_research`)

**What it does**: turns the existing discovery + validation pipeline into a
structured product/category opportunity audit — demand signal, competitor
saturation, supplier availability, landed cost, suggested pricing,
confidence/recommendation, and an honest real-vs-mock data-provenance table.

**Who buys it**: anyone deciding whether to launch a specific product —
your own store, or a client vetting a product idea before committing budget.

**Inputs**: `product_name`, `category`, `retail_price` (optional), `workspace`.

**Outputs**: `ProductAuditResult` — discovery context, validation verdict
(green/yellow/red), supplier quote, pricing breakdown, data provenance,
`status`.

**CLI**: `python -m marketos.cli services product-audit --product "NAME" --category CAT [--price P] [--workspace W] [--json]`

**API**: `POST /api/services/product-audit`

**Report**: *MarketOS Product & Category Opportunity Audit* (markdown, saved
to `state/workspaces/{workspace}/experiments/{id}/report.md`)

**Price range**: 7,500–25,000 MXN basic/pro · 30,000–50,000 MXN deep vertical audit

**Status**: `ready_for_client_service`

---

## 2. Unit Economics (`services.unit_economics`)

**What it does**: margin/break-even/ROAS diagnostic — base margin, optional
geo-adjusted margin, LTV-adjusted margin, break-even CAC, required ROAS
(both derived from the existing margin-calculator's verified formula, not
duplicated math), price-sensitivity scenarios, verdict.

**Who buys it**: anyone who needs a go/no-go on unit economics before
spending on ads or suppliers — also usable as an internal pre-launch gate.

**Inputs**: `product_name`, `supplier_cost`, `retail_price`, `shipping_cost`,
`category`, `geo` (optional), `workspace`.

**Outputs**: `UnitEconomicsResult` — margins, `break_even_cac`,
`required_roas`, `effective_cac`, `verdict` (profitable/breakeven/loss), `status`.

**CLI**: `python -m marketos.cli services unit-economics --product "NAME" --cost C --price P [--shipping S] [--category CAT] [--geo G] [--workspace W] [--json]`

**API**: `POST /api/services/unit-economics`

**Report**: *MarketOS Unit Economics Diagnostic*

**Price range**: 3,000–7,500 MXN template/report · 10,000–25,000 MXN done-for-you · 25,000–60,000 MXN embedded dashboard

**Status**: `ready_for_client_service`

**Ledger-derived variant**: `services.unit_economics.analyzer.from_ledger(product_name, workspace=, supplier_cost=, retail_price=, ...)` — same result shape, but `monthly_ad_spend`/`expected_monthly_revenue` are derived from `backend.ledger`'s replayed commerce events for the workspace instead of the caller supplying them. See `docs/COMMERCE_LEDGER.md`.

---

## 3. E-commerce Operator (`services.ecommerce_operator`)

**What it does**: the launch guard (blocks on missing product validation /
margin analysis / supplier assumptions / budget ceiling / kill criteria /
attribution method / live approval), contribution-profit reconciliation
(ground-truth-reconciled revenue, never inflated platform self-reports),
and kill/scale decisions driven by contribution profit — not ROAS alone.

**Who buys it**: your own e-commerce validation workflow end to end, or a
client's launch-readiness/scale-decision service — see
`docs/OWN_ECOMMERCE_VALIDATION_WORKFLOW.md` for the full 12-step usage.

**Inputs**: `create_commerce_experiment(product_name, validation=, unit_economics=, supplier_assumptions=, kill_criteria=, attribution_method=, workspace=)`, then `evaluate_launch_readiness(envelope, ...)`, `reconcile_contribution_profit(envelope, campaign_revenue=, ground_truth_revenue=, actual_spend=, ...)`, `make_kill_scale_decision(envelope, contribution, roas=, ...)`.

**Outputs**: `LaunchReadiness` (`status=ready_for_client_service`),
`ContributionProfitResult`/`ScaleDecision` (`status=needs_live_data` — these
two genuinely require the caller's real spend/order numbers to be
trustworthy). Decision values: `kill | iterate_offer | iterate_creative | continue_test | scale_cautiously | scale_approved | blocked`, each with an explicit reason.

**CLI**: `python -m marketos.cli services ecommerce-operator --product "NAME" --roas R [--validation-json J] [--unit-economics-json J] [--supplier-assumptions-json J] [--budget-ceiling B] [--kill-criteria-json J] [--attribution-method M] [--proposed-scale-amount A] [--live-action] [--workspace W] [--json]`

**API**: `POST /api/services/ecommerce-operator` — both CLI and API run the same `create_commerce_experiment -> evaluate_launch_readiness -> contribution_profit.from_ledger -> make_kill_scale_decision` pipeline as one call, composing the 4 underlying functions rather than exposing them as 4 separate endpoints (the workflow doc documents each function individually for callers who need finer-grained control).

**Report**: *MarketOS E-commerce Validation Experiment*

**Price range**: 25,000–75,000 MXN (e-commerce validation sprint)

**Status**: `ready_for_client_service` (readiness gate) / `needs_live_data` (contribution-profit + decision, by design)

**Ledger-derived variant**: `services.ecommerce_operator.contribution_profit.from_ledger(envelope)` — same result shape as `reconcile_contribution_profit`, but campaign revenue by channel, ground-truth revenue, spend, orders, refunds, and supplier costs are all derived from `backend.ledger`'s replayed commerce events for the envelope's workspace instead of the caller supplying pre-aggregated scalars. See `docs/COMMERCE_LEDGER.md`.

---

## 4. Creative Growth (`services.creative_growth`)

**What it does**: ad angles + hook-testing matrix (reusing the live
Phase-7 rotation pool plus a free, zero-cost keyword classifier over real
discovery signals), UGC briefs, content-calendar gap detection, creative
fatigue analysis, and a next-batch recommendation.

**Who buys it**: anyone running paid or organic creative testing who wants
a structured testing system instead of ad-hoc creative requests.

**Inputs**: `product_name`, `category`, `signals` (optional), `workspace`.

**Outputs**: `CreativeGrowthPlan` — hooks, angles, hook×angle matrix, UGC
briefs, content calendar status, fatigue report, next-batch recommendation, `status`.

**CLI**: `python -m marketos.cli services creative-growth --product "NAME" [--category CAT] [--workspace W] [--json]`

**API**: `POST /api/services/creative-growth`

**Report**: *MarketOS Creative Testing & UGC Growth System*

**Price range**: 10,000–25,000 MXN strategy pack · 15,000–40,000 MXN monthly retainer · 20,000–60,000 MXN creator seeding setup

**Status**: `ready_for_client_service`

---

## 5. Customer Intelligence (`services.customer_intelligence`)

**What it does**: ICP generation (grounded in this repo's own free,
offline-ingested public-dataset priors — Amazon Reviews 2023 / Olist —
when populated, rather than a fabricated number), customer segmentation,
lead strategy, publicity strategy, and 7 complete vertical playbooks
(real_estate, car_sales, ecommerce_brand, clinic_wellness, home_services,
coaching_consulting, luxury_products).

**Who buys it**: anyone building an acquisition strategy from scratch, or
entering a new vertical.

**Inputs**: `business_type`, `vertical` (optional, one of the 7), `target_geo`, `category`, `workspace`.

**Outputs**: `CustomerIntelligenceSprint` — ICP, segments, lead strategy,
publicity strategy, vertical playbook (buyer profile, pain points,
triggers, offer angles, lead sources, outreach channels, ad angles,
landing-page structure, qualification questions, appointment-setting
logic, monetization model, risks), `status`.

**CLI**: `python -m marketos.cli services customer-intelligence --business-type "TYPE" [--vertical V] [--target-geo GEO] [--category CAT] [--workspace W] [--json]`

**API**: `POST /api/services/customer-intelligence`

**Report**: *MarketOS Customer Acquisition Intelligence Sprint*

**Price range**: 10,000–20,000 MXN basic · 25,000–60,000 MXN full acquisition plan · 60,000–150,000 MXN with automation setup

**Status**: `ready_for_client_service`

---

## 6. Sales Automation (`services.sales_automation`)

**What it does**: chat-based lead qualification (deterministic
keyword/regex slot-filling, no LLM call, no cost), FAQ answering (only from
supplied context, never fabricated), appointment handoff scoring, and
follow-up sequences. **Simulation-only** — no real messaging adapter yet.
See `docs/SALES_AUTOMATION_MODULE.md` for the full design and why.

**Who buys it**: not yet sellable as a standalone client deliverable — see
status below. Useful today for your own internal lead-qualification logic
design/testing.

**Inputs**: `vertical`, `scripted_lead_messages` (a list of strings simulating a lead's messages), `workspace`.

**Outputs**: `ChatSession`, `AppointmentHandoff` (`status=ready_for_internal_use`), qualification flow, follow-up sequence.

**CLI**: `python -m marketos.cli services sales-bot-sim --vertical VERTICAL [--message "..." ...] [--json]`

**API**: `POST /api/services/sales-automation`

**Report**: *MarketOS Appointment Setter Bot Setup Plan*

**Price range**: 30,000–100,000 MXN setup (once real messaging is wired) · 7,500–30,000 MXN monthly retainer · future performance bonus per qualified appointment once tracking exists

**Status**: `ready_for_internal_use` (honest: this is not yet a sellable client service until a real messaging adapter exists)

---

## 7. Digital Products (`services.digital_products`)

**What it does**: converts a MarketOS artifact into a digital-product offer
(10 supported types: template, playbook, course, cohort, ebook, paid
report, prompt pack, calculator, dashboard access, mentorship), builds a
funnel + sales-page structure, generates a content plan (reusing Creative
Growth's angle generator), and computes an honest, clearly-labeled
traffic/conversion validation estimate (verdict: unsafe/fragile/viable/strong)
before you spend on the full build.

**Who buys it**: turning your own results/expertise into a productized
offer; also usable as a client deliverable for anyone launching a digital product.

**Inputs**: `offer_name`, `product_type`, `target_customer`,
`transformation_promised`, `price`, `target_buyers`,
`has_existing_audience`, `workspace`.

**Outputs**: `DigitalProductPlan` — offer, funnel, content plan, validation,
launch checklist, metrics to track, kill/iterate/scale criteria, `status`.

**CLI**: `python -m marketos.cli services digital-product --offer-name "NAME" [--product-type TYPE] [--target-customer TC] [--transformation TP] [--price P] [--target-buyers N] [--has-existing-audience] [--workspace W] [--json]`

**API**: `POST /api/services/digital-product`

**Report**: *MarketOS Digital Product Launch Plan*

**Status**: `ready_for_client_service`

---

## SaaS-lite readiness (Phase 7)

What exists today:
- **Workspace isolation**: every module ties its `CommercialRunEnvelope` and
  `ArtifactStore` paths to a real `workspace_id`; verified with a dedicated
  cross-service integration test (`tests/services/test_workspace_isolation.py`)
  covering all 7 modules plus `ExperimentRegistry.for_workspace()` leak-checking.
- **Client report exports**: every module now actually persists its
  rendered markdown report (not just the JSON result) via
  `services.reporting.save_report_artifacts`; `services.reporting.export_client_report()`
  resolves the on-disk path for handing to a client.
- **API wrappers**: `api/routes/services.py` exposes all 8 modules as clean
  `POST` routes (mounted in `backend/api.py`), matching this repo's existing
  route-module convention. Every route sanitizes non-finite floats
  (`services.reporting.json_safe`) before returning — `core.ugc
  .content_calendar.has_content_gap` legitimately returns `float("inf")` as
  a sentinel, which is valid Python but not valid JSON; `marketos.cli`'s
  `--json` output applies the same sanitizer for the same reason.
- **CLI**: `marketos/cli.py` exposes all 8 modules as subcommands.
- **Commercial status labels**: `services.status.commercial_status()` +
  a `status` field on every module's top-level result, per the table above.

What's explicitly deferred (not built this phase, called out honestly
rather than silently skipped):
- **Full uniform output envelope**: the broader spec asked every function to
  return `{status, summary, recommendations, risk_flags, next_actions,
  report_path, envelope_path, dry_run, errors}` uniformly. Each module
  already returns a `status`, `dry_run`, and a real structured result tied
  to a `CommercialRunEnvelope` (whose `experiment_id` + `ArtifactStore` path
  *are* the envelope/report path) — but retrofitting the exact literal key
  names across all 7 already-tested schemas was judged too invasive/risky
  to do blind at the end of a long session. Flagged here as real, scoped
  future work rather than silently omitted.
- **Real auth/billing/multi-tenant onboarding** — `ClientWorkspace` isolates
  data structurally but there is no login, no API key, no billing meter
  anywhere in this codebase. This is the single largest gap between
  "ready_for_client_service" (the analysis is real) and "self-serve SaaS"
  (anyone could sign up and pay). Explicitly named as `future_saas` in the
  status vocabulary rather than glossed over.
- **Dashboard integration**: `frontend/`'s existing Command Center is wired
  to the orchestrator's own metrics/portfolio/decision endpoints, not to
  these service modules. Adding service-module panels would follow the same
  pattern as the existing dashboard sections (`api/routes/dashboard_panels.py`
  → a new `frontend/src/components/*.tsx`), but no frontend work was done
  this phase — noted as a real gap, not implied to exist.
