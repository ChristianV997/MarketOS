# Amazon Bestsellers Research Adapter

Updated: 2026-10-14  
Module: `backend/adapters/amazon_bestsellers.py`

## Decision

MarketOS no longer scrapes Amazon Best Sellers HTML and no longer promotes
mock rows as observed Amazon evidence.

**SignalEngine integrity:** default `fetch()` returns an **empty list** (cached)
and never emits `amazon_bestsellers_mock` product score rows. Fixture rows are
offline-only via `collect_amazon_bestseller_evidence(mode="fixture")`. Research
consumers that still see mock-tagged rows must reject them; SignalEngine must
not receive fixture scores from this adapter.

Official programmatic access that can expose catalog/sales-rank style fields is
**gated**:

| API | Audience | Relevant capability | Access requirement (official) |
|---|---|---|---|
| Selling Partner API Catalog Items v2022-04-01 | Sellers and vendors | `getCatalogItem` / `searchCatalogItems`, including `salesRanks` | Developer registration + **Product Listing** role |
| Creators API (Associates) | Publishers / affiliates | `SearchItems`, `GetItems`, `GetBrowseNodes` | Amazon Associates enrollment + qualifying sales threshold for API access |

Sources consulted (access date **2026-10-14**):

- https://developer-docs.amazon.com/sp-api/docs/catalog-items-api
- https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction

Neither source documents an ungated public “Best Sellers category page” API
equivalent to the former HTML scrape. Seller-private order/inventory/payment
data is out of scope for general product-opportunity research.

**Architecture choice:** keep a useful **fixture / manual-import** path under
`collect()`; keep an **injected offline transport** contract for future
normalization tests; keep the live gate **disabled by default** and report
`blocked` rather than fabricating endpoints or credentials; keep SignalEngine
`fetch()` empty so synthetic ranks cannot influence production rankings.

## Supported

- `fetch()` → `[]` (empty, non-authoritative SignalEngine path; one-hour cache)
- `collect_amazon_bestseller_evidence(mode="fixture"|"manual_import"|"live")`
- Fixture collect rows labeled: `source=amazon_bestsellers_mock`,
  `evidence_mode=fixture`, `live_validated=false`,
  `rank_semantics=relative_bestseller_rank_not_unit_sales`
- Explicit evidence labels: `evidence_mode`, `live_validated=false`, `network_calls=false`
- Rank semantics label: relative bestseller/sales rank, **not** unit sales, profit, or demand proof
- Injected `live_validated=True` or sales-volume / authority fields on fixture/manual
  input are stripped or forced false (never claim sales volume authority)
- Missing fields stay missing; explicit `rank=0` is preserved
- Currency is never invented for a price

## Unsupported / blocked

- Amazon HTML Best Sellers scraping / browser user-agent collection
- Emitting fixture/mock product scores through SignalEngine `fetch()`
- Treating fixture/mock rows as `observed` or `live_validated`
- Ungated live bestseller browse without official program access
- Live provider HTTP from this lane (even when `MARKETOS_AMAZON_BESTSELLERS_LIVE=1`)
- Using rank as economics input authority

## Consumer notes

`AmazonBestsellersResearchAdapter` in `market_sources.py` already rejects
`amazon_bestsellers_mock` as synthetic. Default `fetch()` is empty so those
rows never reach SignalEngine rankings. Offline demos and contract tests must
call `collect_amazon_bestseller_evidence(mode="fixture")` explicitly.

## Residual CI risk (unowned path)

`tests/test_signal_adapters.py` still contains legacy Amazon cases such as
`test_amazon_fetch_returns_mock_when_network_unavailable`, which assert
`len(fetch()) > 0` and product/score keys. That file is **outside this PR’s
ownership**. With integrity-correct `fetch()=[]`, those adjacent tests will fail
until a separate owner updates them to expect an empty SignalEngine list (or
moves fixture assertions to `collect()`). Documented here as residual merge
risk / next operator action; do not reintroduce fixture scores into `fetch()`
to satisfy that legacy expectation.

## Live gate

Environment:

- `MARKETOS_AMAZON_BESTSELLERS_LIVE=1` required for live-mode entry
- `allow_network=True` required
- Injected transport must expose `fetch_catalog_ranks` and `offline_fixture=True`

Otherwise status is `blocked` / `fixture_only`.
