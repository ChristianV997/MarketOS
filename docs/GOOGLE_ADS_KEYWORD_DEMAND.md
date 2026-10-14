# Google Ads keyword demand (read-only)

Access date for the primary pages below: **2026-10-14**.

This adapter plans and parses **historical keyword demand** from Google Ads Keyword Planner. It is not the Google Trends adapter, not relative interest, and not the DataForSEO `keyword_demand_snapshot`. It does not create campaigns, forecasts, or ad groups, and it does not spend.

The operational command is [scripts/run_google_ads_keyword_demand.py](../scripts/run_google_ads_keyword_demand.py). It has no `--fixture` flag and does not read environment variables. If approval, credentials, or the live transport are missing, the report is `blocked` or `unavailable` with **zero observations**. It does not invent keywords.

Live HTTP is **not implemented** in this version. `DisabledLiveTransport` never opens a socket. Satisfying every gate still returns `blocked_live_transport_not_implemented`, `network_calls: false`, `credentials_loaded: false`, `live_evidence: false`, and `fixture_fallback: false`. That is intentional until a credential broker with its own owner exists.

## What an operator must have

Do not paste tokens, customer ids, or developer tokens into the repo, the request JSON, logs, or chat.

1. A Google Ads account and a Google Cloud project whose access level is one of Test, Explorer, Basic, or Standard. Basic and Standard need brand verification. Apply in the Cloud project, not by minting a new developer token in the Ads API Center.
2. OAuth for scope `https://www.googleapis.com/auth/adwords` (verified on the v26 `GenerateKeywordIdeas` RPC). Store the refresh material in the existing server-side credential broker. This repo only accepts a boolean `credential_reference_present` and a non-numeric `customer_reference_id` such as `credential-google-ads-customer`.
3. An Approval Ledger `provider_call` record in status `approved`. The ledger itself stays offline.
4. Recorded terms review and privacy review for storing aggregate keyword metrics only.
5. Acknowledgement of the published rate limit and of the fact that **no per-request price** was on the pages reviewed.
6. An explicit geography and language. This adapter does not default to the United States or English. Use `geoTargetConstants/{criterion_id}` (at most 10) or set `all_locations: true` for the documented empty-list behavior. Use `languageConstants/{criterion_id}` or set `language_unspecified: true`. Set `keyword_plan_network` to `GOOGLE_SEARCH` or `GOOGLE_SEARCH_AND_PARTNERS`.

Example request (metadata only):

```json
{
  "method": "generate_keyword_historical_metrics",
  "keywords": ["thermal printer"],
  "geo_target_constants": ["geoTargetConstants/1000001"],
  "language_constant": "languageConstants/1003",
  "keyword_plan_network": "GOOGLE_SEARCH",
  "customer_reference_id": "credential-google-ads-customer",
  "authorization": {
    "approval_status": "approved",
    "credential_reference_present": true,
    "cloud_project_access_level": "basic",
    "terms_review_complete": true,
    "privacy_review_complete": true,
    "quota_limit_acknowledged": true,
    "cost_unknown_acknowledged": true
  }
}
```

`geoTargetConstants/1000001` and `languageConstants/1003` in that example are placeholders for ids the operator looks up. They are not a default.

Exit 0 means a report file was produced. Read `result_status`. It does not mean Google returned demand.

## Verified from primary docs

- Keyword planning overview: planning services allow fewer requests per minute than other services; cache results because they do not change frequently; historical metrics refresh monthly. Forecasts are a different operation and are out of scope here.
  https://developers.google.com/google-ads/api/docs/keyword-planning/overview
- `GenerateKeywordIdeas`: `KeywordSeed` is 1–20 keywords; `KeywordAndUrlSeed` is 1–20 plus a URL; `SiteSeed` can yield up to 250,000 ideas (this adapter rejects site seed). Locations: up to 10 geo target constants, or an empty list for all locations. Language resource form: `languageConstants/{criterion_id}`. Pagination: up to 10,000 results per page; follow `next_page_token`. Sample REST call: `POST https://googleads.googleapis.com/v${API_VERSION}/customers/${CUSTOMER_ID}:generateKeywordIdeas` with `Authorization: Bearer` and `login-customer-id`.
  https://developers.google.com/google-ads/api/docs/keyword-planning/generate-keyword-ideas
- `GenerateKeywordHistoricalMetrics`: up to 10,000 keywords and up to 10 geos. Fields used here: `avg_monthly_searches` (trailing 12 months or `year_month_range`), `monthly_search_volumes`, `competition`, `competition_index` 0–100, `low_top_of_page_bid_micros` (20th percentile), `high_top_of_page_bid_micros` (80th percentile), and `average_cpc_micros` only when `include_average_cpc` is requested. A missing count stays null. The Java sample prints null when the count is absent.
  https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics
- Quotas (page last updated 2026-10-14 UTC): `GenerateKeywordIdeas`, `GenerateKeywordHistoricalMetrics`, and `GenerateKeywordForecastMetrics` are limited to 1 request per second per CID. 1 QPS is 60 requests per 60 seconds. Excess calls return `RESOURCE_EXHAUSTED`. `GenerateAdGroupThemes` is 2 QPS and is not implemented. Daily API operations by Cloud project access level: Test 15,000/day against test accounts; Explorer 2,880/day production and 15,000 test; Basic 15,000 both; Standard unlimited. These are quotas, not a price and not a grant that this repo may call Google.
  https://developers.google.com/google-ads/api/docs/best-practices/quotas
- Sunset timetable: v26 released 2026-10-14, sunset November 2027. v26.1 is listed under upcoming versions (October 2026), not as released. This module pins the documented released version **v26** only.
  https://developers.google.com/google-ads/api/docs/sunset-dates
- Developer token policy: tokens were sunset on 2026-09-09. Access level follows the Google Cloud project that owns the OAuth client or service account. Sending a developer-token header is optional and ignored. Some post-sunset Basic or Explorer upgrades fail with `AUTHORIZATION_ERROR` (known issue on that page).
  https://developers.google.com/google-ads/api/docs/api-policy/developer-token
- OAuth scope on the v26 RPC: `https://www.googleapis.com/auth/adwords`.
  https://developers.google.com/google-ads/api/reference/rpc/v26/KeywordPlanIdeaService/GenerateKeywordIdeas
- `Money.amount_micros` (v26 RPC): "One million is equivalent to one unit," and `Money` also has `currency_code`.
  https://developers.google.com/google-ads/api/reference/rpc/v26/Money

## Unknown, or not on the pages reviewed

- No per-request or monthly Ads API unit price. Do not invent one. `cost_unknown_acknowledged` is required so a run cannot pretend the call is free.
- The historical-metrics guide names `*_micros` bid fields but does not include `currency_code` on those fields. This adapter stores the integer, sets `currency` to null, and does **not** divide by one million. The Money rule above is for the `Money` message; it is not treated as a currency conversion of keyword metrics.
- The full `competition` enum member list was not on the historical-metrics page. Tokens are preserved. They are not mapped to a closed LOW/MEDIUM/HIGH set and they are not scores.
- The OAuth introduction still says a developer token is required to make Ads API calls. The developer-token policy page, updated for the 2026-09-09 sunset, says the header is optional and ignored. This adapter follows the policy page: it does not collect, store, or send a developer token. It does not claim the older sentence is false; it refuses to handle the secret.
- Whether v26.1 shipped later on 2026-10-14 after the sunset page was updated. This module does not call v26.1.
- Whether an omitted language or network has a server-side default. This adapter requires an explicit choice and does not send US or English by default.
- Account currency for a historical bid. Not present in the metric. Not labeled USD.

## Adapter bounds that are not Google limits

Google allows 20 seed keywords, 10,000 historical keywords, 10 geos, and 10,000 idea results per page. This module allows at most 50 keywords, page size 100, and 2 pages, so a test double cannot pull an unbounded set. A capped page is `incomplete`, not a full census.

`search_growth_signal` stays null. Monthly search counts are not written into the canonical 0–1 attention score. `available_for_canonical_scoring` stays false. No shared ConsumerAttention schema is edited.

## Rollback

This lane adds only:

- `evaluation/commerce/google_ads_keyword_demand_adapter.py`
- `scripts/run_google_ads_keyword_demand.py`
- `tests/test_google_ads_keyword_demand_adapter.py`
- `docs/GOOGLE_ADS_KEYWORD_DEMAND.md`

Revert that commit. Do not merge this branch to enable a live call.
