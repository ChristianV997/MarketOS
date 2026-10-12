# Brief-Driven Product Opportunity Research

Offline, fixture/fake-client runner that turns a short research brief into a
source-attributed Product Opportunity Synthesis result. It does **not** require
manual competitor URLs, supplier CSVs, or hand-entered observations.

## Brief fields

| Field | Required | Meaning |
| --- | --- | --- |
| `product_query` | yes | Product or search phrase to research |
| `category` | yes | Category / vertical label |
| `target_region` | yes | Target market / region |
| `language` | yes | Language / locale for attention framing |
| `intended_buyer` | yes | Buyer persona the offer is for |
| `max_candidates` | no | Bound (1–25, default 5) |
| `evidence_mode` | no | `fixture_demo` (default) or `manual_import` |
| `workspace_id` | no | Optional workspace label for governor simulation |

## Source statuses

Every pillar (`marketplace`, `supplier`, `consumer_attention`) returns exactly
one of:

- `collected` — usable records returned
- `partial` — some records returned with incomplete coverage
- `not_configured` — no client/credentials/fixtures wired
- `disabled_by_policy` — blocked by policy before collection
- `timed_out` — exceeded the per-source timeout
- `unavailable` — client error or empty failure
- `quota_exhausted` — governor/quota style refusal

Successful pillars are kept when a sibling fails. Missing evidence is never
translated into zero demand, zero cost, or a favorable claim.

## Run

```bash
python scripts/run_brief_driven_product_research.py \
  --product-query "portable espresso maker" \
  --category "kitchen appliances" \
  --region US \
  --language en \
  --intended-buyer "home baristas" \
  --use-fixture-demo \
  --json
```

Without `--use-fixture-demo`, sources default to `not_configured` and synthesis
still returns an honest empty/partial decision package.

## Authorities reused

- Marketplace normalize/build: `backend.adapters.research.marketplace_trends`,
  `evaluation.commerce.marketplace_trends.build_report`
- Supplier normalize/build: `backend.adapters.research.supplier_feasibility`,
  `evaluation.commerce.supplier_feasibility.build_report`
- Attention normalize/build: `backend.adapters.research.consumer_attention`,
  `evaluation.commerce.consumer_attention.build_report`
- Decision layer: `evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis`
- Bounds: `evaluation.companyos.resource_execution_governor.evaluate_execution_request`

Pillars stay separate: marketplace price/availability is not verified demand;
supplier cost/logistics is not attention proof; attention is never supplier
proof. Currencies are listed and never converted; no FX rate is invented.
Price, CPA, CTR, budget, and similar figures remain planning assumptions when
present in synthesis thresholds.

## What requires future approval or credentials

- Human-approved Approval Ledger policy before any live provider adapter
- Credential **references** (never secret values) for marketplace/supplier/attention providers
- Terms/privacy and output-contract review per provider
- Resource Execution Governor budgets/quotas for provider pulls

Simulated or offline approval in this runner does **not** authorize live calls.
`execution_authorized` remains `false`.

## Safety

- Default: fixture/fake clients only
- No credential reads, provider network calls, customer PII, raw payload persistence,
  scheduling, API routes, or frontend changes in this lane
