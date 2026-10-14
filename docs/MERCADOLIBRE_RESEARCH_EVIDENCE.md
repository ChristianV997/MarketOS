# Mercado Libre Listing Evidence

This contract uses the existing `backend.adapters.mercadolibre_trends` seam and
`evaluation.commerce.marketplace_trends.MarketplaceTrendEvidence`. It introduces
no scorer, economics implementation, provider registry, FX conversion, or live
transport. All examples and tests use synthetic fixture responses.

## Operator and Caller Contract

- `fetch()` without a transport raises the existing `AdapterFetchError`, with
  `error_type="unavailable"`, code `mercadolibre_live_access_blocked`, and no retry.
  SignalEngine records the failure. Its existing all-source-failure fallback can
  still emit separately labeled `source="mock"` rows; these are not Mercado Libre
  observations. The research source worker records the blocked source and can
  retain successful results from other sources.
- An explicitly injected **offline fixture transport** supports
  `get(url, params=..., timeout=...)`, returning a response with `status_code`,
  `iter_content(chunk_size=...)`, and `close()`. The implementation is trusted
  test/import code, not a network authorization capability. Do not inject a live
  HTTP client. No built-in HTTP client, credential lookup, environment activation
  switch, or live approval bypass exists.
- `fetch(transport=..., sites=["MLM"], queries=["desk light"],
  observed_at="2026-10-01T12:00:00+00:00")` returns allowlisted listing dictionaries.
  `evidence_mode` accepts only `fixture` or `manual_import`. Success with no rows
  returns `[]`; failure with no usable rows raises a stable error. Partial results
  have `status="partial"` and static failure/rejection warnings. Provider response
  bodies and exception messages never enter error text or logs.
- `to_marketplace_evidence(item, "MLM", candidate_id="desk-light", ...)` projects
  one snapshot row or one fetched observation to the **existing evidence type**.
  A domain candidate binding is required; listing IDs and display names never
  select one automatically. Fetched observations retain their evidence mode,
  observation time, and source identity; conflicting overrides are rejected.
- For a collection of fetched observations, use `project_marketplace_evidence(records,
  candidate_bindings={source_reference: candidate_id})`, then the existing
  `evaluation.commerce.marketplace_trends.build_report(evidence, evidence_mode="manual_import")`
  builder for manual imports (use `"fixture"` for fixtures). Missing
  bindings fail closed. The projection rejects conflicting observations for a
  source, including title/permalink changes before projection discards them,
  and deduplicates identical observations before the shared report sees
  them. Do not assemble arbitrary conflicting single-row projections directly:
  the shared builder's equal-quality duplicate tie remains order-dependent and
  is outside this adapter's scope.
- `MercadoLibreResearchAdapter.to_canonical` rejects listing-only input with
  `listing_evidence_is_not_sales_velocity`. The trend store requires numeric
  velocity and confidence; a cumulative sales count or caller-provided velocity
  scalar cannot meet that contract. Other research adapters are unchanged.

## Evidence Semantics

| Value | Meaning |
|---|---|
| Missing/null price | `None`, with unavailable provenance; never zero-filled |
| Explicit zero | Preserved as `0.0`, with a warning; does not claim a free offer |
| Currency | Supplied uppercase three-letter `currency_id`; missing remains `None` |
| Observation time | Explicit timezone-aware import/collection time, normalized to UTC; never replaced by listing creation/update time or the current clock |
| Listing identity | Validated site-prefixed item ID; source reference is `/items/{id}` |
| Variation identity | Explicit `variation_id` stays separate; the reference fragment `#variation-{id}` is a local identity qualifier, not a provider request parameter |
| Sold quantity | Optional provider-reported count without a verified measurement window; no revenue, demand, intent, score, or velocity is inferred |
| Available quantity | Optional referential quantity; not exact inventory, supplier capacity, or replenishment proof |
| Shipping | Optional `free_shipping` boolean claim; false and missing remain distinct; no shipping price is inferred |
| Region/language | Unavailable unless separately evidenced; not inferred from site or query |
| Confidence | Unavailable; no probability or provider confidence is invented |

Normalized rows retain vetted HTTPS listing permalinks and canonical source
references. Duplicate source observations collapse deterministically; conflicting
observations for the same item/variation are quarantined in either order.
Variants are never combined. No cross-call cache remains. Previously saved
discovery snapshots are not retroactively reclassified by this adapter change;
old scores must not be treated as live evidence.

The existing evidence dataclass has string-shaped missing currency/time and a
numeric confidence default. The projection uses empty strings and `0.0` with
explicit `field_provenance="unavailable"`; that confidence placeholder is not a
measured confidence. The snapshot source-type name `mercadolibre_trends_snapshot`
is retained for compatibility, while all fields and warnings describe listings.
Unknown rank, growth, bestseller status, and confidence remain unsupported.

## Bounds and Failure Handling

Policy limits are three sites, six distinct queries, three pages per pair, and
18 total requests; 20 results/page; 120 characters/query; a timeout argument in
`(0, 8]` seconds; 256 KiB actually read per response; and 1 MiB serialized output.
The 256 KiB policy is sized for 20 bounded listing observations, not a claim about
Mercado Libre's maximum response. Oversized snapshots are rejected, not truncated.
JSON duplicate keys, non-finite numbers, malformed UTF-8, depth over 10, and node
count over 10,000 fail closed. Monetary/count values must be finite, nonnegative,
and at most `1e15`; counts must be integral. Prices that cannot round-trip through
the existing float-shaped evidence contract are rejected, including positive
underflow to zero. JSON decimal values are retained until that validation.
No sleeps or retries occur.

The timeout is a fixture transport contract argument, not an independent thread
or process watchdog for arbitrary injected code. Returned response streams close
on success, malformed data, size rejection, HTTP errors, and interruptions.
401/403/429 are distinguished from empty success. No provider-specific request
quota has been verified; the request limit is MarketOS policy.

## Official Documentation

Accessed **2026-10-13**, via official documentation/search-index excerpts; some
direct documentation opens were unavailable. No provider API request was made.

- [Items and searches](https://developers.mercadolibre.com.mx/es_ar/envio/items-y-busquedas)
  (updated 2026-09-10): search endpoint examples use bearer authorization; public
  availability quantities are referential ranges. Listing search ordering is not
  proof of sales velocity or demand. Item examples pair prices with currency IDs.
- [Authentication and authorization](https://developers.mercadolibre.com.mx/es_ar/como-empezar/autenticacion-y-autorizacion):
  application/user authorization is required for OAuth access. Exact search
  entitlement/allowlisting for a future app is unverified.
- [Domains and categories](https://developers.mercadolibre.com.mx/en_us/categories-and-listings)
  (updated 2025-10-06): site identity and `default_currency_id` metadata. A site
  default is not the currency of an observation. The adapter supports a bounded
  subset: MLA, MLM, MLB, MLC, MCO, MLU, MPE; endpoint entitlement is not implied.
- [Trends](https://developers.mercadolibre.com.mx/en_us/trends/trends)
  (updated 2026-07-29): dedicated `/trends` endpoints exist and return weekly
  keyword/URL entries. They are separate from listing search and are not fetched
  or inferred by this adapter.
- [Highlights](https://developers.mercadolibre.com.mx/mas-vendidos-en-mercado-libre):
  bestseller ranking is a separate resource/entity contract, not unit sales.
- [429 guidance](https://developers.mercadolibre.com.mx/en_us/manage-questions-answers/rate-limit-429-error):
  future approved clients need bounded rate-limit handling; exact search RPM is
  unverified. This release makes zero live calls and performs zero retries.

Historical "no auth/live" Mercado Libre descriptions in `CREDENTIALS_SETUP.md`
and `OPERATIONS.md` do not describe this revised implementation. `OPERATIONS.md`
is owned by PR #459 and is intentionally not edited here; its owner should update
that entry when this contract lands.

## Validation and Future Activation

Run:

```powershell
python -m pytest -q tests/test_mercadolibre_trends.py tests/test_signal_adapters.py tests/test_research_trend_adapter.py tests/test_marketplace_trends.py
```

The tests also exercise the existing canonical
marketplace report and signal/research callers with fake responses only.

Future network integration requires an approved Approval Ledger request, budget
and quota policy, credential-reference handling, application access, terms/privacy
review, output-contract tests, and separate live-transport review. Nothing here
grants supplier verification, spend, outreach, publishing, orders, or launch.
