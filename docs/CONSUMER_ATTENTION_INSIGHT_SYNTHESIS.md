# Offline Consumer Attention Insight Synthesis

This layer converts already-normalized search-interest, ad-library, review, and
comment signals into structured demand themes, objections, audience/context
hints, and evidence-backed product questions.

It is not a provider adapter, a scorer, or an opportunity authority. Product
Opportunity Synthesis remains the only fusion/ranking authority. Insights can
be attached to that report; they do not change its score or recommendation.

## What each insight keeps

Every theme, objection, hint, and question retains:

- source and platform
- geography and language, or an explicit missing-context note
- observation window and freshness
- aggregate engagement, review, and view counts where they were supplied
- evidence class (`fixture`, `manual_import`, `observed`, `stale`, `conflicting`, `unavailable`)

Ads, reviews, comments, and search trends stay in separate signal families.
Contradictory observation values and opposing sentiment are preserved. Missing
geography or time is reported as uncertainty; it is never filled in.

## What it refuses

- An engagement, view, or review count is not purchase intent.
- Attention is not supplier proof, stock, shipping, or launch authorization.
- A supplied claim that says "proven demand" or "supplier verified" is flagged
  as unsupported and is not promoted into a theme.
- No live collection, credentials, scraping, publishing, or customer messaging.

## Run it

```powershell
python scripts/run_consumer_attention_insights.py tests/fixtures/consumer_attention/google_trends_fixture.json --as-of 2026-09-10T00:00:00Z
python scripts/run_consumer_attention_insights.py --markdown
```

The default path reads local JSON and prints a report. It does not call a
network or write a file unless `--output` is a relative path.

## Opportunity workflow

`build_product_opportunity_synthesis(..., consumer_insights=report.to_dict())`
attaches the insight report under `consumer_attention_insights` and leaves the
recommendation unchanged. Product validation can take the same object and add
its product questions to `open_questions`.

Prior art reviewed for this slice included review-mining research and public
insight libraries. None was adopted: those systems either use licensed corpora,
embeddings, or live collection. This implementation is original, stdlib-only,
and bound to the merged `evaluation.commerce.consumer_attention` contract.
