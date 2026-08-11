# CJ public-page supplier evidence

Phase 1's selected, real, public/no-auth supplier-evidence source, grounding
Commerce MVP unit economics in an observed supplier cost instead of a pure
assumption whenever one can be found.

## What this is — and isn't

This is a *different* data path from `backend.validation.suppliers`'s
`CJDropshippingClient`, which already wraps CJ's **authenticated** catalog
API (`CJ_EMAIL` + `CJ_API_KEY`, OAuth-style token exchange). This module
(`backend.adapters.research.cj_public_evidence`) reads only CJ's **public**
product pages — no login, no API key, no session, nothing that requires an
account. The two are related only by supplier name; nothing here touches
the authenticated client's token manager, and every event/record this
module produces is tagged `source: cj_public_page`, never
`cj_dropshipping`, so the two are never silently conflated.

Why both exist: the authenticated API needs a CJ account and credentials
nobody has configured yet (that remains later, credentialed work per the
Phase 1 task brief). The public path works today, with no account, and is
the thing this document is about.

## Static-first extraction and optional Crawl4AI fallback

Crawl4AI (Apache-2.0, Playwright-based) remains optional rather than part of
the default API image. The Phase 1 live validation harness reached public
CJ and storefront hosts, but static requests produced no usable Product
records. That result justified a narrow fallback, without making browser
rendering the default transport.

The fallback is enabled only when both of these operator controls are set:

```bash
MARKETOS_PHASE1_JS_RENDER=1
CRAWL4AI_ALLOWED_DOMAINS=www.cjdropshipping.com
```

The competitor adapter uses the same explicit domain allowlist, for example
`CRAWL4AI_ALLOWED_DOMAINS=www.wacaco.com,aeropress.com`. Crawl4AI still
checks robots.txt, keeps its bounded raw cache, emits only canonical Product
records, and never follows a path to mutation, login, or provider APIs. If
the package is absent, the page is disallowed, the allowlist is missing, or
rendering fails, the evidence result remains degraded and no value is
inferred.

The static-first decision and fallback boundary are supported by this
evidence:

- `requirements-oss.txt` now carries the pinned `crawl4ai==0.8.6` optional
  profile after the live harness justified a JS-rendering fallback. It is
  still not part of the default API image; install it only in an operator
  environment that can provide the reviewed browser runtime.
  `docs/oss/LICENSE_MANIFEST.yml` records its license
  (Apache-2.0-with-attribution) as reviewed, but it was never actually
  wired into `requirements.txt` or installed. This module doesn't change
  that status.
- This development sandbox's own network egress policy blocks
  `cjdropshipping.com` (and almost every other general web domain) at the
  proxy `CONNECT` level — confirmed directly against the proxy's own
  status endpoint, which reported `connect_rejected` / "policy denial" for
  every attempt, not a CJ-side anti-bot response. That means Crawl4AI's
  Playwright-driven browser extraction against a real CJ page could not be
  exercised or verified in this environment at all, regardless of whether
  it was installed.
- `requests`, `beautifulsoup4`, and `lxml` are already first-class,
  installed dependencies (`requirements.txt`). A `requests`-based adapter
  needs zero new dependencies, zero new browser binaries, and zero new
  Railway/container deployment weight (no Playwright/Chromium install
  step). Given the Crawl4AI decision couldn't be empirically validated
  here anyway, the lower-footprint option was the responsible choice for
  this contribution.
- `backend/adapters/research/crawl4ai.py` already exists in the repo as
  an optional adapter with exactly the right extraction philosophy
  (JSON-LD-only `schema.org Product` parsing, domain allowlist, robots.txt
  enforcement, dry-run gate, TTL/capacity-bound cache, explicit
  `unit_cost` vs `selling_price` separation). This module **reuses its
  JSON-LD parser directly** (`Crawl4AIResearchAdapter._product_records_from_jsonld`)
  rather than duplicating it, and mirrors the rest of its safety pattern
  with `requests` instead of Crawl4AI's browser.

The Phase 1 fallback is now the natural bounded upgrade path. The
`fetch_product_evidence` and `fetch_competitor_offer` call sites invoke the
existing adapter only after static extraction fails and the two gates are
present. The evidence models, provenance rules, event vocabulary, and
economics wiring remain transport-agnostic.

If a future session in an environment with real network access to
`cjdropshipping.com` finds that CJ's product pages require JS rendering to
expose structured data (this could not be determined here — see "Real
smoke result" below), Crawl4AI remains the natural upgrade path: the
`fetch_product_evidence`/`discover_candidate_urls` call sites in
`backend/mvp_commerce/supplier_evidence.py` are the only integration
points that would need to swap transports; the evidence model, provenance
rules, event vocabulary, and economics wiring are all transport-agnostic.

## Extraction architecture

`backend/adapters/research/cj_public_evidence.py`:

1. **URL safety** — `_validate_public_url` rejects non-http(s) schemes,
   any host outside `{cjdropshipping.com, www.cjdropshipping.com}`
   (the one selected Phase 1 supplier host), and resolves DNS to reject
   private/loopback/link-local/reserved/multicast destinations (an SSRF
   guard against DNS rebinding, not just a string check on the literal
   hostname).
2. **robots.txt** — `_check_robots` fetches and enforces the target host's
   `robots.txt` via `urllib.robotparser`; an unreadable robots.txt blocks
   rather than proceeding.
3. **dry-run gate** — `SidecarContext(dry_run=True)` (the default
   everywhere this module is called from) short-circuits to a fully
   degraded, honest result before any network call. Nothing here performs
   live I/O unless a caller explicitly opts in, matching every other
   public-network capability in this repository
   (`backend.signals.public_sources.ingest_public_rss`'s `allow_network`,
   `MVP_ISLAND.md`'s manual-approval/real-signal policy).
4. **bounded fetch** — `_bounded_get`: fixed timeout (10s default),
   2MB response-size cap, a fixed descriptive User-Agent, and **redirects
   are rejected, not followed** (a redirect target is unvalidated by
   definition — the safest "redirect policy" is not one that trusts an
   unseen destination).
5. **extraction** — JSON-LD `schema.org Product` objects only, via the
   shared parser in `crawl4ai.py`. A page without a valid `Product` object
   yields no evidence — the module never turns page prose into a claimed
   fact.
6. **caching** — TTL (900s default) + capacity-bound (100 entries
   default) in-process cache, same shape as `crawl4ai.py`'s.
7. **discovery** — `discover_candidate_urls` is explicitly marked
   best-effort/unverified: it looks for plain `<a href="/product/...">`
   links in whatever HTML a bounded GET to CJ's search page returns. If
   CJ's search results are JS-rendered, this legitimately returns an empty
   list rather than guessing — **operator-supplied CJ product URLs remain
   the reliable Phase 1 path.**

## Provenance model

Every `CJProductEvidence` record carries `field_status: dict[str, str]`,
one entry per commercially meaningful field (`title`, `price`, `sku`,
`category`, `variants`, `weight_kg`, `inventory_status`,
`warehouse_origin`, `shipping_cost`, `estimated_delivery_days`,
`quality_evidence`, `rating`, `reviews_count`, `images`, `description`),
each one of: `observed`, `derived`, `assumed`, `unavailable`, `malformed`,
`stale`, `conflicting`. A field is `"observed"` only when the page's own
structured data actually supplied it — nothing here infers a plausible
value to fill a gap. `confidence` is the observed-field ratio; unknowns
lower it, they are never treated as favorable evidence.

For economics integration, evidence normalizes down into the existing
canonical contracts (`evaluation.contracts.SupplierOffer`/
`ProductCandidate`/`DataQuality`) rather than inventing a second
"economics" model — `to_supplier_offer`/`to_product_candidate`.

**A CJ product page's displayed price is treated as the supplier unit
cost**, not a retail selling price. This is a deliberate departure from
`crawl4ai.py`'s general-purpose caution (which assumes an arbitrary
scraped site is a retail storefront, where price ≠ wholesale cost): CJ is
specifically a wholesale/dropship supplier catalog, so the price shown is
what MarketOS would pay to source the item.

## Real vs assumed Commerce MVP economics

`backend/mvp_commerce/runner.py::_economics()` (the original, 100%
assumption-based function every existing caller uses) is **unchanged**. A
new, purely additive function, `_economics_with_evidence()`, is used only
when a caller explicitly supplies a `SupplierEvidenceResult`
(`backend.mvp_commerce.supplier_evidence.gather_supplier_evidence`):

- **Observed supplier cost/shipping** (from a CJ public page with
  `field_status["price"] == "observed"`) **overrides** the assumed
  defaults for that specific component only.
- Missing components (e.g. shipping was never exposed) keep the existing
  assumption unchanged.
- `UnitEconomicsSummary.assumptions` records exactly which component was
  observed vs assumed, per field — e.g.
  `"Observed CJ supplier cost=9.5 (source=https://www.cjdropshipping.com/product/...)"`
  next to `"Assumed shipping=6.0"` in the same summary.
- `UnitEconomicsSummary.source` becomes `"partial_observed_supplier_evidence"`
  instead of `"dry_run_assumption"` whenever any component was observed.

Precedence, exactly as specified: **observed > derived > explicit
assumption > unknown.** Nothing here ever infers a number that wasn't
either observed or an explicit, disclosed assumption.

## Canonical events

Reuses the existing `backend.contracts.events.Event`/
`backend.events.repository.EventRepository` system — no second event
store. New event types, following `public_signal_event()`'s exact
dry-run/advisory/non-authoritative metadata shape:

| Event type | Aggregate | When |
|---|---|---|
| `supplier_evidence_requested` | `commerce_mvp_run` | Every attempt, before results are known |
| `supplier_product_observed` | `supplier_product` | A priced candidate was found |
| `commerce_economics_enriched` | `commerce_mvp_run` | Unit economics used observed evidence |
| `supplier_evidence_degraded` | `commerce_mvp_run` | No usable evidence was found |

## API / operator surface

`POST /api/commerce-mvp/public-run` gains `attempt_supplier_evidence: bool`
and `supplier_candidate_urls: list[str]` (max 5). It is a no-op unless
**both** the server sets `MARKETOS_SUPPLIER_EVIDENCE_LIVE=1` **and** the
request opts in — the same double-gate pattern as
`MARKETOS_PUBLIC_COMMERCE_RUNS`/`allow_public_network`. The response gains
`supplier_evidence_attempted: bool`.

`GET /api/events/supplier-evidence` is a thin `event_type` filter over the
existing timeline (no second query engine) — the generic
`GET /api/events?event_type=supplier_product_observed` already works
without this, this route is operator convenience.

## Commands

```bash
python -c "
from backend.adapters.research.cj_public_evidence import fetch_product_evidence
from backend.contracts.adapters import SidecarContext
print(fetch_product_evidence('https://www.cjdropshipping.com/product/<id>.html',
      context=SidecarContext(dry_run=False)).to_dict())
"
```

Enable the live path on a running server: set
`MARKETOS_SUPPLIER_EVIDENCE_LIVE=1`, then call `/api/commerce-mvp/public-run`
with `attempt_supplier_evidence: true` and `supplier_candidate_urls`.

## Failure modes

| Condition | Result |
|---|---|
| Host not `cjdropshipping.com` | Rejected before any network call (`rejected:...`) |
| DNS resolves to a private/internal IP | Rejected (`rejected:...`) |
| `dry_run=True` (default) | Simulated, zero network calls |
| robots.txt disallows the path, or is unreadable | Blocked (`robots_blocked:...`) |
| Redirect response | Rejected, not followed |
| Response exceeds 2MB | Rejected |
| Network error / timeout | Degraded (`fetch_failed:...`) — never raises |
| No JSON-LD `Product` object on the page | Degraded (`no_structured_product_data_found`) |
| JSON-LD present but no price | `field_status["price"] = "unavailable"`, economics keep the assumption |

Every failure mode above degrades to a structurally valid
`CJProductEvidence` with all fields `"unavailable"` — nothing raises to a
caller, and nothing fabricates a number.

## Real smoke result (honest report, not a fixture claim)

A real-network smoke attempt against `https://www.cjdropshipping.com` was
made from this development sandbox. It did **not** reach CJ: the sandbox's
own outbound network gateway rejected the `CONNECT` to
`www.cjdropshipping.com:443` with a 403 at the policy layer (confirmed via
the proxy's own diagnostics endpoint — `"kind": "connect_rejected"`,
`"detail": "gateway answered 403 to CONNECT (policy denial or upstream
failure)"`). The same block applied to unrelated third-party domains
(Amazon, AliExpress, Wikipedia all failed to connect too), confirming this
is a general sandbox egress restriction, not something CJ-specific and not
a bug in this adapter. `pypi.org`/`files.pythonhosted.org`/`api.github.com`
remained reachable throughout (those are on this sandbox's proxy bypass
list), which is how the license/version research for this document was
done.

**What this means concretely:** the adapter's URL-safety, robots.txt,
dry-run gate, caching, JSON-LD parsing, and degradation logic are all
exercised by real tests (`tests/test_cj_public_evidence.py`) against
in-memory fixture HTML, not a live CJ response — this is honest, verified
behavior. What remains genuinely unverified is whether CJ's real product
pages actually expose `schema.org Product` JSON-LD (the extraction method
this module relies on) — that can only be confirmed from an environment
with real network access to `cjdropshipping.com` (Railway, or a local
machine). Running the one-liner in "Commands" above from such an
environment against a real CJ product URL is the next concrete validation
step, called out explicitly in the final report's "highest-leverage next
task."

## Migration path to authenticated CJ API

If/when `CJ_EMAIL`/`CJ_API_KEY` credentials become available,
`backend.validation.suppliers.CJDropshippingClient` already implements the
authenticated catalog API and remains the system of record for anything
that needs it (order placement, authoritative pricing at scale). This
public-page module stays useful as a corroborating, no-credential evidence
source and a fallback when the authenticated API is rate-limited,
misconfigured, or intentionally not yet enabled for a workspace — the two
are designed to coexist, not to be merged into one client.
