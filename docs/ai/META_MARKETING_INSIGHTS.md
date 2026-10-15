# Meta Marketing API Insights

Schema: `MarketOS.MetaMarketingInsightsEvidence.v1`

Authorized-account performance only. This is not PR #489's public Ad Library, not market-wide demand, and not verified sales.

Pages consulted on 2026-10-14:

| Source | Fact used |
| --- | --- |
| [Ads Insights API](https://developers.facebook.com/docs/marketing-api/insights/), updated 2026-04-27 | `GET` insights for an ad account, campaign, ad set, or ad. Examples use Graph `v26.0`. Sample fields include `date_start`, `date_stop`, `impressions`, and `spend`. |
| [`ads_read`](https://developers.facebook.com/docs/permissions/reference/ads_read) | Reads insights for an account the app owns or was granted. |
| [Ad account insights](https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights), updated 2026-08-06 | `account_currency` is the account currency. `POST` creates an AdReportRun and is not implemented. |
| [Limits and best practices](https://developers.facebook.com/docs/marketing-api/insights/best-practices/), updated 2026-05-05 | Dates use the ad account timezone. Insights refresh about every 15 minutes and do not change after 28 days of being reported. No numeric quota is stated. |
| [Error codes](https://developers.facebook.com/docs/marketing-api/insights/error-codes/), updated 2026-05-21 | `4/1504022` is too many requests. `100/3191001` is permission. |
| [Metric update](https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/), effective 2026-01-12 | `7d_view` and `28d_view` are deprecated. No attribution window is requested. |

Unknown: the numeric rate quota, the maximum custom `time_range`, an IANA timezone name, and the retention duty.

## Gate

`provider_call` in `evaluation.companyos.approval_ledger` is `blocked_in_current_mode` with a zero per-run and monthly budget. `simulate_action("provider_call")` cannot execute. `RESEARCH_CREDENTIAL_KEYS` contains only `TIKTOK_ACCESS_TOKEN` and `TIKTOK_ADVERTISER_ID`. A boolean approval flag is not accepted, and no Meta key is added to the allowlist. Operational reads do not call a transport and do not fill the gap with a fixture.

`build_blocked_get_plan` describes a `GET /insights` request with the documented aggregate fields. It stores no account id, requests no attribution window, and sets `post_allowed` false. The plan stays blocked by the ledger.

## Consumption

`account_performance_view` releases rows only when the document is a supplied fixture, the evidence category is `ProviderRunEvidence`, the data scope is `authorized_advertiser_account_only`, and the claimed use is `account_performance_review`. `market_demand`, `competitor_intelligence`, `product_opportunity_attention`, `verified_sales`, and `ad_launch` release no metrics. Error and empty documents are not releasable. This is not an input to product-opportunity attention or the Ad Library contract.

## Rollback

Revert the commit that added the four owned files, or delete them. Do not merge.
