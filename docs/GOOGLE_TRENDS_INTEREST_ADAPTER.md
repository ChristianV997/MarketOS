# Google Trends Organic Search-Interest Adapter v1

Offline contract / fixture / fake-transport layer for **official** Google
Trends **relative search-interest** evidence used in product-opportunity research.

Results are **relative / consistently scaled search interest only**. They are
not search volume, sales, supplier proof, purchase intent, or launch evidence.

## Primary sources (official Google documentation only)

| Source | Role |
|---|---|
| [Google Trends API alpha](https://developers.google.com/search/apis/trends) | Public product landing: alpha access, high-level capabilities |
| [Introducing the Google Trends API (alpha)](https://developers.google.com/search/blog/2025/07/trends-api) (2025-07-24) | Public announcement: scale semantics, window, aggregations, geo |
| [Can't access the Trends API docs](https://developers.google.com/search/apis/trends/help/cant-access-docs) | Confirms detailed reference docs are gated to accepted alpha testers |

No Pytrends, scraping, undocumented endpoints, proxies, credentials, or live calls.

## Confirmed vs unknown (public pages only)

| Topic | Status | What public docs establish |
|---|---|---|
| Official API exists | **Confirmed** | Google Trends API alpha on Search Central |
| Commercially GA | **No / unknown as GA** | Alpha tester applications; limited roll-out; not production-ready for everyone |
| Alpha access | **Confirmed required** | Apply for early access; access opened on a rolling, limited basis |
| Metric semantics | **Confirmed relative interest** | “numbers don't reflect absolute numbers, they reflect search interest”; consistently scaled across requests; **not** the Trends website per-request 0–100 rescale |
| Time window | **Confirmed (announced)** | Rolling ~1800 days (~5 years); data up to about 2 days ago |
| Aggregations | **Confirmed (announced)** | Daily, weekly, monthly, yearly |
| Geography | **Confirmed (announced)** | Region and sub-region per ISO 3166-2 |
| Language filter | **Unknown** | Not stated on the public pages reviewed |
| Endpoint URLs / RPC names | **Unknown** | Detailed docs gated; not on public landing/blog |
| Auth method / OAuth scopes | **Unknown** | Not published on public pages |
| Quotas / unit pricing / SLA | **Unknown** | Not published on public pages |
| Exact response field schema | **Unknown** | Behind alpha reference docs |

`REQUEST_KINDS` such as `interest_over_time` / `interest_by_region` are **adapter
request-shape labels**, not confirmed Google method identifiers.
`max_terms` / `max_requests` on the request plan are **fixture/dry-run caps**, not
published API limits (public pages only say the API can compare “dozens” of terms).

## What this module does

- Records accurate access limits (alpha gate; gated reference docs; missing
  public pricing/quotas/methods).
- Parses sanitized fixtures into normalized relative-interest observations with
  geography, observation period, method, and provenance. Language is kept as
  adapter observation metadata without claiming public API confirmation.
- Distinguishes `collected`, `unavailable`, `disabled_by_policy`, `incomplete`,
  `stale`, plus transport outcomes `rate_limited`, `quota_exhausted`,
  `unsupported_access`.
- Keeps missing points as `null` / `unavailable` — never coerces to zero.
- Preserves observation-window provenance (`observation_period_start` /
  `observation_period_end`, resolution, collected_at / freshness).
- Keeps attention / relative-interest evidence separate from marketplace price,
  supplier proof, purchase intent, and launch authority.

## What it does not do

- No network calls, SDKs, credentials, `.env` values, or secret material.
- No database persistence, UI, routes, planners, scorers, or new provider paths.
- No edits to DataForSEO, consumer-attention importers, discovery registries,
  or `backend/discovery/ad_intelligence.py`.
- No live provider validation or GA claim.

## Commands

```text
python scripts/run_google_trends_interest_adapter.py --json
python scripts/run_google_trends_interest_adapter.py --markdown
python scripts/run_google_trends_interest_adapter.py --fixture tests/fixtures/google_trends_interest_adapter/trends_interest_valid.json --json
python scripts/run_google_trends_interest_adapter.py --transport-scenario unsupported_access --json
```

## Before any transport can be enabled

1. Alpha (or later GA) access granted; gated reference docs readable for the project.
2. Capture then-current official endpoint/method/auth, quotas, and pricing (still
   unknown on public pages today).
3. Metadata-only credential reference + Approval Ledger `provider_call`.
4. Separately reviewed fail-closed live transport with output-contract tests.
5. Keep **relative search-interest** labeling; never upgrade to absolute volume,
   sales, supplier proof, or launch authority.
