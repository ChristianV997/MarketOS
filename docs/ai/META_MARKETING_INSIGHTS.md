# Meta Marketing API Insights

Schema: `MarketOS.MetaMarketingInsightsEvidence.v1`

Read-only aggregate reporting for an operator's own authorized ad account. This is not PR #489's public Ad Library contract, not consumer attention, and not verified sales.

## What official pages support

| Source | Fact used |
| --- | --- |
| Ads Insights API, updated 2026-04-27 | `GET` insights on an ad account, campaign, ad set, or ad. Examples use Graph `v26.0`. A sample row has `date_start`, `date_stop`, `impressions`, and `spend`. `clicks` is a documented field. |
| `ads_read` permission reference | The permission reads Ads Insights for ad accounts the app owns or was granted. Dashboard analytics is an allowed use. |
| Ad account insights reference | `account_currency` is the ad account currency. `POST` creates an AdReportRun. This adapter does not send that `POST`. |
| Limits and best practices, updated 2026-05-05 | Error `4` / `1504022` means too many requests. No numeric quota is stated on that page. |
| Metric update, 2025-10-16 | From 2026-01-12, `7d_view` and `28d_view` are deprecated. This adapter does not request an attribution window. |

## What is not claimed

The numeric rate limit, the maximum custom `time_range`, the retention duty, and whether `date_start` is UTC or the ad account timezone are unknown. Platform `actions` are not independently verified sales and are not purchase intent.

## Gate

`backend.research.credentials.RESEARCH_CREDENTIAL_KEYS` has no Meta key. Operational reads return `approval_unavailable` or `credential_unavailable`, do not call a transport, and do not fill the gap with a fixture. `normalize_supplied_insights` only maps a caller-supplied document.

## Rollback

Delete this note, `evaluation/commerce/meta_marketing_insights.py`, `backend/adapters/research/meta_marketing_insights.py`, and `tests/test_meta_marketing_insights.py`. Do not merge.
