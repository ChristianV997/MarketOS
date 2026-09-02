# Product Opportunity Synthesis v1

Product Opportunity Synthesis is the decision layer over the existing three
offline evidence pillars: marketplace demand and pricing, supplier feasibility
and landed-cost scenarios, and consumer attention with creative evidence.

DataForSEO search and shopping summaries can feed opportunity context in
fixture mode through the existing evidence interfaces. They are supplemental
search/competitor signals, not supplier proof, live validation, or launch
authorization.

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

**SYN-GRADE-LIVE-LABEL fix:** `A_live_validated` used to require only that
*any one* of the three supplied pillars carried a live-looking `evidence_mode`
-- so a single live-labeled pillar mixed with two fixture/manual pillars still
graded as professionally live-validated. It now requires an explicit live
attestation (`live_readonly`, `public_live`, or `authenticated_live`) on
*every* supplied pillar. Three populated pillars alone is never sufficient,
and a single fixture/manual pillar caps the grade at `C_fixture_or_partial`
even when another pillar claims live evidence. Genuinely all-live evidence
still reaches `A_live_validated`; the grade was tightened, not disabled.

**Evidence-label consistency (found during a follow-up review):** the first
pass only checked the *candidate's* embedded evidence/offer `evidence_mode`,
never the pillar *report's own* top-level `evidence_mode` field -- so a
report that labeled itself `fixture_demo` at the top level while an embedded
evidence item claimed `live_readonly` (or the reverse) still graded as
`A_live_validated`, an internally self-contradictory result. The grade now
requires the pillar report's top-level label to agree with its own evidence
items before counting as live.

**SYN-ALIAS-NO-COLLAPSE fix:** two candidates in the same pillar report that
share both `query` and an evidence/offer `source_family` (an existing
provenance field, not a new one) are now collapsed into a single scored
candidate, so a correlated alias of the same product/source family is never
ranked twice. `query` text alone never triggers a collapse -- many distinct
products share a plain search query -- so this cannot merge genuinely
different candidates. Every collapse is recorded in a new `alias_notes` field
on the report; a score mismatch between the kept candidate and its alias is
called out explicitly there rather than picked silently.

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

After the Launch Draft Pack, `scripts/generate_site_draft_pack.py` can produce a portable implementation blueprint without selecting or mutating a storefront platform.
## CompanyOS handoff

Opportunity synthesis can be referenced by the offline CompanyOS Department Layer. Management uses it to prioritize work; Finance uses service-package assumptions; Sales uses it for a draft offer and handoff. The reference is advisory and does not authorize launch or outreach.
# Portfolio governance

Opportunity synthesis feeds the Resource & Execution Governor. Scores, supplier feasibility, attention evidence, unit economics, and portfolio fit determine whether an opportunity can proceed to deep validation, launch drafting, or a bounded experiment.
