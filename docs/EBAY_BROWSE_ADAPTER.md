# eBay Browse API evidence adapter

`backend.adapters.research.ebay_browse` is the eBay-specific adapter for an existing MarketOS research brief. It uses the official eBay Buy Browse API `item_summary/search` request shape, with an injected transport so offline tests never call eBay.

## Contract

- Input: a brief containing `candidate_id` (or `id`) and a product `query`/`product_query`; optional `category`, `target_market`, and `language` are appended to the bounded query.
- Output: existing `evaluation.commerce.marketplace_trends.MarketplaceTrendEvidence`, using `source_type="ebay_public_listing_snapshot"` and `evidence_mode="live_readonly"` for a permitted provider read.
- Current listings are competition/pricing observations only. Listing count, price, availability, variants, and shipping claims are **not** bestseller status, sales velocity, verified demand, or supplier proof.
- Missing Browse fields remain unavailable and are not synthesized.
- Duplicate `itemId` values are collapsed deterministically; malformed rows are ignored.

## Safety and bounds

`EbayBrowseConfig` requires a non-secret credential reference and bounds timeout (0.1–30 seconds), page size (1–50), pages (1–3), query length, and variants. The adapter is disabled by default for network use: `allow_network=True` and `approval_granted=True` are required in addition to configuration. Live transport is injected by the caller; no credential value is read or logged here. Auth, timeout, malformed response, and unexpected transport failures return safe status codes and no raw provider payload.

The current implementation does not make live calls. Tests use synthetic Browse-shaped responses. To activate a real transport, complete the repository's Approval Ledger, credential-reference, budget, terms/privacy, output-contract, timeout/retry, workspace isolation, and independent transport review gates first. eBay Browse API documentation: <https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search>.

## OSS and dependency review

This vertical uses only Python standard-library parsing and the existing MarketOS contracts; it adds no SDK or runtime dependency. An official eBay API client is therefore not copied or adopted. Any future client must be reviewed for license, maintenance, transitive dependency, credential handling, and security posture before use. No unofficial proxy or scraping is permitted.
