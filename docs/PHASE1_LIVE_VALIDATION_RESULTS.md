# Phase 1 live validation results

## Paired static versus JS benchmark

This is a bounded, read-only benchmark of the optional Crawl4AI fallback. It
does not prove demand, supplier viability, profitability, launch readiness, or
general access to public commerce pages.

- Runtime: CPython 3.12.
- Optional renderer: Crawl4AI 0.8.6 with an explicitly selected local Chrome
  channel.
- Inputs: one CJ Dropshipping product page, one Shopify competitor product
  page, the AeroPress manufacturer product page, and the Wacaco product page.
- Access: public/no-auth GETs only; no credentials, provider mutations, or
  browser-access-control bypasses.

| Metric | Static | JS-rendered |
| --- | ---: | ---: |
| Reachable hosts | 4 | 4 |
| Observed supplier fields | 0 | 0 |
| Observed competitor offers | 0 | 1 |
| Pricing coverage | 0.00 | 0.25 |
| Overall evidence completeness | 0.00 | 0.25 |
| Overall confidence | 0.4364 | 0.4478 |
| Run quality | low | low |
| Assumption percentage | 0.8333 | 0.8333 |

The JS-rendered AeroPress page produced a normalized public competitor offer:
title, USD price, brand, availability, rating, review count, and shipping cost
were observed. Static extraction observed no competitor offers from the same
four-host set.

## CJ public-page diagnosis

The same CJ URL was fetched and rendered successfully, but the returned page
was a non-product shell rather than a product document:

- no schema.org Product JSON-LD was present;
- no product, price, SKU, inventory, or portable-espresso terms were present
  in rendered HTML/text;
- visible text was minimal and embedded state exposed Cloudflare/runtime
  markers rather than a product record;
- no login or CAPTCHA prompt was detected.

No raw HTML, page text, embedded state, or customer data is retained in this
repository. The diagnostic retained only field-presence booleans and hashes in
the local, uncommitted validation workspace.

## Interpretation and next boundary

JS rendering is useful for partially viable public competitor evidence. It is
not yet sufficient for CJ supplier evidence in this environment: the public
CJ page rendered without usable product data, so there is no mapper defect to
harden from this sample. Do not infer supplier cost, inventory, shipping,
weight, or dimensions.

The next bounded investigation should evaluate an authenticated **read-only**
supplier source (CJ API or Zendrop MCP) before implementation. It must remain
environment-configured, manual, read-only, and separately approved; no orders,
payments, fulfillment, customer messages, or provider writes are authorized.
