# Amazon Bestsellers Research Adapter

Updated: 2026-10-14  
Module: `backend/adapters/amazon_bestsellers.py`

## Decision

MarketOS no longer scrapes Amazon Best Sellers HTML and no longer promotes
mock rows as observed Amazon evidence.

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

**Architecture choice:** keep a useful **fixture / manual-import** path; keep an
**injected offline transport** contract for future normalization tests; keep the
live gate **disabled by default** and report `blocked` rather than fabricating
endpoints or credentials.

## Supported

- `fetch()` → fixture rows for SignalEngine compatibility (`source=amazon_bestsellers_mock`)
- `collect_amazon_bestseller_evidence(mode="fixture"|"manual_import"|"live")`
- Explicit evidence labels: `evidence_mode`, `live_validated=false`, `network_calls=false`
- Rank semantics label: relative bestseller/sales rank, **not** unit sales, profit, or demand proof
- Missing fields stay missing; explicit `rank=0` is preserved
- Currency is never invented for a price

## Unsupported / blocked

- Amazon HTML Best Sellers scraping / browser user-agent collection
- Treating fixture/mock rows as `observed` or `live_validated`
- Ungated live bestseller browse without official program access
- Live provider HTTP from this lane (even when `MARKETOS_AMAZON_BESTSELLERS_LIVE=1`)
- Using rank as economics input authority

## Consumer notes

`AmazonBestsellersResearchAdapter` in `market_sources.py` already rejects
`amazon_bestsellers_mock` as synthetic. Fixture-only `fetch()` therefore remains
non-authoritative for research ingestion, which is intentional.

## Live gate

Environment:

- `MARKETOS_AMAZON_BESTSELLERS_LIVE=1` required for live-mode entry
- `allow_network=True` required
- Injected transport must expose `fetch_catalog_ranks` and `offline_fixture=True`

Otherwise status is `blocked` / `fixture_only`.
