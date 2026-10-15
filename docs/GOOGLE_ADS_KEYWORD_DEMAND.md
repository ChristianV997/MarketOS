# Google Ads keyword metrics (read-only)

Access date for the re-check below: **2026-10-15**. Pages that still show "Last updated 2026-10-14 UTC" are cited as that page date.

This adapter plans and parses **approximate historical Google Search metrics** from Keyword Planner. It is not the Google Trends adapter, not relative interest, and not the DataForSEO `keyword_demand_snapshot`. Counts are not sales, observed product demand, product attention, or marketplace truth. The module does not create campaigns, forecasts, or ad groups, and it does not spend.

## Mexico live-read decision: NO-GO

No authorized Google Ads request has been made from this repo, and the live socket is not implemented. A synthetic or fixture transport cannot validate a Mexico read. Do not describe any current output as live Mexico demand.

A later live read would still have to clear every item below. Missing any one keeps the report blocked with zero observations:

1. Approval Ledger `provider_call` is `approved`.
2. Credential broker has the OAuth material. This JSON only carries `credential_reference_present: true` and a non-numeric `customer_reference_id`.
3. Cloud project access is Explorer, Basic, or Standard, and `target_account_environment` is `production`. Test access can call test accounts only and is not a production Mexico read. Test accounts do not serve live ads.
4. `keyword_research_use_permitted` is true. Basic and Standard permissible use is what allows keyword research; access level alone does not.
5. Terms and privacy reviews cover aggregate keyword metrics only.
6. Quota and unknown-cost acknowledgements are set. No per-request price was published on the pages reviewed.
7. Geography is an explicit `geoTargetConstants/{id}` for Mexico, copied from the official geo-target table by the operator. This repo did not find a Mexico criterion id on the pages fetched on 2026-10-15, so it does not hardcode one. `languageConstants/1003` is the published Spanish (`es`) constant and is not applied unless the request sets it. English in the official sample is `languageConstants/1000` and is not a default.
8. Network is explicit. The v26 historical-metrics request says that if network is omitted, Google Search and Partners is used. This adapter does not rely on that default.
9. `as_of` is the operator's reference month. Without it, freshness stays `unverified_no_reference_clock`. A window more than 48 months before `as_of`, or a window after `as_of`, is rejected. Forty-eight months is this adapter's reading of "up to the past 4 years," not a Google-published day count.
10. The call is direct or through a manager. The ideas sample sends `login-customer-id`. This module does not accept that id. Whether a non-manager account may omit it was not settled on the pages reviewed.

`DisabledLiveTransport` still returns `blocked_live_transport_not_implemented` after every gate is true.

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
    "cost_unknown_acknowledged": true,
    "keyword_research_use_permitted": true,
    "target_account_environment": "production"
  }
}
```

`geoTargetConstants/1000001` is a placeholder, not a Mexico id. `languageConstants/1003` is the published Spanish constant and is still not a default.

Exit 0 means a report file was produced. Read `result_status`. `synthetic_not_live` is a test double, not a live validation. `collected` is not a status this module emits.

## Verified from primary docs

- Keyword planning overview, last updated 2026-10-14 UTC: cache results because responses for a given keyword set stay consistent over hours or days, and historical search volume refreshes monthly. Forecasts are a different operation.
  https://developers.google.com/google-ads/api/docs/keyword-planning/overview
- Historical metrics, last updated 2026-10-14 UTC: past Google Search performance, not a forecast. `avg_monthly_searches` is the past 12 months or `year_month_range`. `monthly_search_volumes` is approximate and available for up to the past 4 years. `competition_index` is 0–100. Bid fields are 20th and 80th percentile `*_micros`. `average_cpc_micros` only when requested. The sample uses geo `2840` for the USA and language `1000` for English; those are sample constants, not this adapter's defaults. A missing count stays null.
  https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics
- v26 `GenerateKeywordHistoricalMetricsRequest`, last updated 2026-10-13 UTC: up to 10 geos; an empty list may mean all geos; omitted network means Google Search and Partners; omitted language includes keywords across languages; near-exact duplicates may be collapsed (`car` / `cars`); maximum 10,000 keywords. `customer_id` is "the ID of the customer with the recommendation." No `currency_code` field is on this request message's historical metrics.
  https://developers.google.com/google-ads/api/reference/rpc/v26/GenerateKeywordHistoricalMetricsRequest
- Access levels, last updated 2026-10-14 UTC: Test is test accounts only, 15,000 operations/day. Explorer is test and production, 2,880 production operations/day. Basic is 15,000 for both. Standard is unlimited for both. The page summary says three levels; the table lists four, including Explorer. Permissible use, for Basic and Standard, controls features such as keyword research.
  https://developers.google.com/google-ads/api/docs/api-policy/access-levels
- Language constants, codes and formats page, last updated 2026-10-14 UTC: Spanish `es` is criterion id 1003.
  https://developers.google.com/google-ads/api/data/codes-formats
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
