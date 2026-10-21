# eBay Browse API evidence adapter

`backend.adapters.research.ebay_browse` is the eBay-specific adapter for an existing MarketOS research brief. It targets the official eBay Buy Browse API `item_summary/search` request shape.

## Contract

- Input: a brief containing `candidate_id` (or `id`) and a product `query`/`product_query`; optional `category`, `target_market`, and `language` are appended to the bounded query.
- Output: existing `evaluation.commerce.marketplace_trends.MarketplaceTrendEvidence`, using `source_type="ebay_public_listing_snapshot"`.
- `transport_kind="fixture"` (default for injected demo/test transports) emits `evidence_mode="fixture"` and `network_calls=false`. Fixture/fake rows are never reported as live.
- `transport_kind="live"` is reserved for `LiveEbayBrowseTransport` and only labels `evidence_mode="live_readonly"` when a live transport actually runs. Live network use stays blocked until Approval Ledger authorization succeeds.
- Current listings are competition/pricing observations only. Listing count, price, availability, variants, and shipping claims are **not** bestseller status, sales velocity, verified demand, or supplier proof.
- Missing Browse currency stays empty/unknown (`field_provenance.currency=unavailable`). The adapter never defaults missing currency to USD and never invents FX.
- `source_confidence` stays `0.0` (no fabricated score). Provenance is carried in `field_provenance`.
- Requested `marketplace_id` is validated against supported `EBAY_*` IDs, sent as `X-EBAY-C-MARKETPLACE-ID`, and retained on listings/evidence (`site_id`). Listing marketplace mismatches are warned, not silently adopted.
- Duplicate `itemId` values are collapsed deterministically; malformed rows are ignored.

## Authorization and live transport

Live activation requires all of:

1. `transport_kind="live"`
2. non-secret `credential_ref`
3. `allow_network=True`
4. `evaluate_ebay_browse_authorization()` → Approval Ledger `simulate_action("provider_call")` with `authorized=True` (offline ledger currently always denies live provider calls)
5. an injected `LiveEbayBrowseTransport` (or compatible `kind="live"` transport) with a token resolver

Caller-supplied booleans or forged `authorized=True` decisions cannot escalate past the ledger. The offline Approval Ledger cannot grant live provider execution; the adapter therefore remains fail-closed for network I/O and exposes the unmet prerequisites on `approval_denied` results.

`LiveEbayBrowseTransport` performs a read-only GET to `/buy/browse/v1/item_summary/search` with `Authorization: Bearer <token>` and `X-EBAY-C-MARKETPLACE-ID`. Token material comes only from a caller-provided resolver keyed by `credential_ref`; this module never opens `.env` files or logs secrets. OAuth client-credentials exchange stays outside this module (resolver responsibility). `MAX_RETRIES` is explicitly `0` until a reviewed retry policy exists. HTTP 401/403 → `auth_failed`, 429 → `rate_limited`, timeouts → `timeout`.

No orders, purchases, inventory mutation, seller messaging, ads, publishing, or other write operations are implemented.

## Official documentation

- Browse `item_summary/search`: <https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search>
- Browse API overview: <https://developer.ebay.com/api-docs/buy/browse/overview.html>
- OAuth client credentials grant: <https://developer.ebay.com/api-docs/static/oauth-client-credentials-grant.html>
- Buy marketplace IDs (`X-EBAY-C-MARKETPLACE-ID`): <https://developer.ebay.com/api-docs/buy/static/ref-marketplace-id.html>

Access requirements (official): create an eBay developer application, obtain OAuth credentials, request the Buy Browse scope via client-credentials grant, and call the production (`api.ebay.com`) or sandbox host with a marketplace ID header. Rate/quota limits are application-specific in eBay’s developer portal; this adapter surfaces HTTP 429 as `rate_limited` and does not retry by default.

## Safety and bounds

`EbayBrowseConfig` bounds timeout (0.1–30 seconds), page size (1–50), pages (1–3), query length, variants, and marketplace ID. Auth, timeout, rate-limit, malformed response, and unexpected transport failures return safe status codes and no raw provider payload.

## OSS and dependency review

This vertical uses Python standard-library HTTP/JSON parsing and existing MarketOS contracts; it adds no SDK. Any future official eBay client must be reviewed for license, maintenance, transitive dependency, credential handling, and security posture before use. No unofficial proxy or scraping is permitted.
