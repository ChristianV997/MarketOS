# Google Trends Organic Search-Interest Adapter v1

Offline contract / fixture / fake-transport layer for **official** Google
Trends relative search-interest evidence used in product-opportunity research.

## Source evaluation (primary docs only)

| Question | Finding |
|---|---|
| Official API? | **Yes — Google Trends API alpha** ([Trends API](https://developers.google.com/search/apis/trends), [announcement 2025-07-24](https://developers.google.com/search/blog/2025/07/trends-api)) |
| Commercially GA? | **No.** Access is alpha-tester application only; limited roll-out; public docs describe it as not production-ready for everyone. |
| Relative interest time series? | **Yes.** Consistently scaled search interest; aggregations daily / weekly / monthly / yearly; rolling ~1800-day window; data up to ~2 days ago; ISO 3166-2 geos. |
| Published quotas / unit pricing? | **Not on the public landing pages** reviewed for this adapter. Treated as unavailable fields. |
| Allowed acquisition paths here? | Official API contract only. **No** Pytrends, browser scraping, undocumented endpoints, or proxies. |

**Decision:** Implement this official Trends interest vertical as a fail-closed
fixture/dry-run adapter. No non-overlapping official GA alternative publishes
the same *relative* organic search-interest time series. Google Ads keyword
historical metrics are absolute volume estimates (different category; would
overlap DataForSEO keyword demand) and were not selected.

## What this module does

- Records accurate access limits (alpha gate, missing GA pricing/quotas).
- Parses sanitized fixtures into normalized relative-interest observations
  with geography, language, observation period, method, and provenance.
- Distinguishes `collected`, `unavailable`, `disabled_by_policy`, `incomplete`,
  `stale`, plus transport outcomes `rate_limited`, `quota_exhausted`,
  `unsupported_access`.
- Keeps missing points as `null` / `unavailable` — never coerces to zero.
- Keeps attention evidence separate from marketplace price, supplier proof,
  purchase intent, and launch authority.

## What it does not do

- No network calls, SDKs, credentials, `.env` values, or secret material.
- No database persistence, UI, routes, or new scoring formulas.
- No edits to DataForSEO, consumer-attention importers, discovery registries,
  or `backend/discovery/ad_intelligence.py`.
- No live provider validation.

## Commands

```text
python scripts/run_google_trends_interest_adapter.py --json
python scripts/run_google_trends_interest_adapter.py --markdown
python scripts/run_google_trends_interest_adapter.py --fixture tests/fixtures/google_trends_interest_adapter/trends_interest_valid.json --json
python scripts/run_google_trends_interest_adapter.py --transport-scenario unsupported_access --json
```

## Future activation (out of scope here)

1. Confirm GA (or approved alpha) access on a Google Cloud project.
2. Capture published scopes, quotas, and pricing from Google’s then-current docs.
3. Metadata-only credential reference + Approval Ledger `provider_call`.
4. Separately reviewed live transport with output-contract tests.
5. Keep relative-interest labeling; never upgrade to absolute volume or launch authority.
