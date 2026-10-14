# Amazon Bestsellers Research Adapter

Updated: 2026-10-14  
Module: `backend/adapters/amazon_bestsellers.py`

## Capability decision

**Category Best Sellers discovery for MarketOS multi-client commercial product
research is `unavailable`.** Amazon does not document a commercially eligible
API that returns category Best Sellers rank *lists* comparable to Amazon Best
Sellers pages. This adapter therefore does **not** implement a live bestseller
feed, does not scrape HTML, and does not silently serve fixtures as operational
research.

| Capability | Decision | Notes |
|---|---|---|
| Category bestseller discovery / rank feed | **Unavailable** | No documented list/feed endpoint |
| Catalog item lookup + per-item `salesRanks` | Adjacent, gated | SP-API Catalog Items; not a bestseller feed |
| Offer / price / availability | Adjacent, gated | Creators Offers / SP-API pricing in authorized contexts |
| Seller-owned orders / inventory | Out of scope | Seller-authorized SP-API only |

### Official sources (access date **2026-10-14**)

- https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference — `salesRanks` / `classificationRanks` are **per catalog item**
- https://developer-docs.amazon.com/sp-api/docs/role-mappings — Catalog Items need **Product Listing** role (seller/vendor)
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction — Creators API requires Associates + qualifying sales
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/search-items — `SortBy` values are `AvgCustomerReviews`, `Featured`, `NewestArrivals`, `Price:*`, `Relevance` (**no BestSellers**)
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/get-browse-nodes — browse-node hierarchy only

Do **not** relabel Creators `SearchItems` or SP-API per-ASIN `salesRanks` as a
category Best Sellers feed.

## Operational behavior (live-data-first)

- `fetch()` → always `[]` for SignalEngine. Status via `last_fetch_status()` /
  readiness: `unavailable` / `unavailable_no_category_bestseller_api`.
- Default `collect_amazon_bestseller_evidence()` → `mode="unavailable"`: empty
  records, precise blockers, `live_validated=false`, `network_calls=false`.
- Fixtures require **explicit** `mode="fixture"` (tests/demo only).
- Manual snapshots require **explicit** `mode="manual_import"`.
- `allow_network=True` and `MARKETOS_AMAZON_BESTSELLERS_LIVE=1` are **not**
  Approval Ledger authority and do not invent a bestseller endpoint.
- Live HTTP to Amazon is not performed in this lane.

## Supported (explicit offline only)

- `collect(..., mode="fixture")` — synthetic rows labeled
  `source=amazon_bestsellers_mock`, `evidence_mode=fixture`, never live
- `collect(..., mode="manual_import")` — operator-supplied rows, not live Amazon
- Injected offline transport normalization for contract tests
  (`offline_fixture=True`); warnings state it is **not** live bestseller discovery
- Rank semantics: relative rank, **not** unit sales, profit, demand, supplier, or launch authority
- Missing fields stay missing; explicit `rank=0` preserved; currency never invented

## Unsupported / blocked

- Amazon HTML Best Sellers scraping
- Silent fixture fallback on operational paths
- Treating fixture/manual/offline rows as `observed` or `live_validated`
- Fabricating a category bestseller list from catalog search or per-ASIN ranks
- Using rank as economics / launch authority

## Approval and credentials

Future live work (if Amazon documents a compliant feed, or MarketOS rescopes to
an adjacent capability with distinct evidence meaning) still requires:

1. CompanyOS Approval Ledger (`provider_call` / `web_data_acquisition`)
2. Credential registry metadata (no secret values in repo)
3. Resource Execution Governor budget/rate caps
4. TrustOS provider/privacy gates

A boolean `allow_network` alone is never sufficient.

## Consumer notes

`AmazonBestsellersResearchAdapter` in `market_sources.py` rejects
`amazon_bestsellers_mock`. Operational `fetch()` is empty, so Amazon fixture
scores cannot enter SignalEngine rankings. Product Opportunity Synthesis must
not treat empty Amazon fetch as positive demand evidence.

### Unowned CI dependency

`tests/test_signal_adapters.py::test_amazon_fetch_returns_mock_when_network_unavailable`
still expects non-empty mock rows. That file is outside this PR’s write set
(also touched by PR #495). Integrity-correct `fetch()=[]` fails that adjacent
test until a separate owner updates it. Do not restore fixture scores into
`fetch()` to green CI.

## Recommended adjacent alternative (distinct meaning)

If the product needs Amazon catalog signals later, evaluate a separately named
**per-ASIN sales-rank / catalog-search** evidence contract (SP-API or Creators),
with Approval Ledger + credentials, and never brand it as category Best Sellers
discovery.
