# Product Opportunity Synthesis v1

Product Opportunity Synthesis is the decision layer over the existing three
offline evidence pillars: marketplace demand and pricing, supplier feasibility
and landed-cost scenarios, and consumer attention with creative evidence.

It is not a fourth evidence engine. It reuses existing scores and provenance,
applies transparent weights, and produces one client and operator decision
package.

## Run it

```powershell
python scripts/run_product_opportunity_synthesis.py --json
python scripts/run_product_opportunity_synthesis.py --markdown
python scripts/run_product_opportunity_synthesis.py `
  --marketplace-trend-report artifacts/marketplace_trends/latest/marketplace_trend_report.json `
  --supplier-feasibility-report artifacts/supplier_feasibility/latest/supplier_feasibility_report.json `
  --consumer-attention-report artifacts/consumer_attention/latest/consumer_attention_report.json `
  --output artifacts/opportunity_synthesis/latest `
  --markdown
```

The command is offline-only, requires no credentials, and writes nothing unless
`--output` is supplied. Output is sanitized to the synthesis JSON and Markdown,
a client action checklist, and an operator decision summary.

## Score and confidence

The combined opportunity score is a transparent weighted join:

```text
marketplace opportunity * 0.40
+ supplier feasibility * 0.35
+ consumer attention * 0.25
```

Confidence grades communicate evidence quality rather than business certainty:
`A_live_validated`, `B_multi_source_manual`, `C_fixture_or_partial`,
`D_low_confidence`, and `F_reject_or_missing`. Fixture/manual evidence can
recommend validation or a launch draft for human review, but never authorizes
launch, ad spend, posting, orders, payments, or provider mutations.

## Decision rules

Poor margin, high saturation, and low or objection-heavy attention take
precedence over a high raw demand score. Missing supplier proof produces
`validate_supplier_first`; missing marketplace or consumer evidence produces
the corresponding research action. Partial logistics produces
`expand_supplier_research`. A high score with low risk may produce
`advance_to_launch_draft`, still with an evidence disclaimer.

The report includes an evidence matrix, source report status, price band,
landed-cost and break-even scenarios when available, confidence, pillar risks,
kill/scale thresholds, and a fourteen-day validation plan. CPA, CTR,
add-to-cart, budget, and scale thresholds are planning assumptions, not live
performance data or spend authorization.

## Consulting use

This is the premium decision layer for the Product Validation Report. It helps
a client understand which candidate ranks first, why it ranks first, what is
still unknown, and what bounded validation should happen next. It can support a
$500–$1,000 consulting package when a human reviews source provenance and
assumptions before delivery. The next productized step is a Launch Draft Pack
after read-only supplier proof; it remains separate from this offline report.
## Next commercial deliverable

When synthesis identifies a candidate worth drafting, use `scripts/generate_launch_draft_pack.py` to turn the existing evidence into client-reviewable launch assets. The pack is deterministic and offline; it inherits price, margin, hooks, objections, risks, and thresholds rather than creating a new score. Supplier proof and human approval remain required.
