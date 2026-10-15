# TikTok Research Evidence (commercial-attention capability)

Default-off capability contract for TikTok consumer-attention / creative
evidence. It does **not** call TikTok, load credentials, scrape Creative
Center, or authorize ads, spend, messaging, or publishing.

**Operational result for MarketOS Mexico commercial product-attention research:**
there is **no eligible official live source** under current primary docs.
Ordinary runtime returns zero evidence rows with a precise blocked status.
That is a **source-capability boundary**, not a claim that MarketOS itself must
be offline. Offline fixtures/fakes are test/demo only (`allow_offline_demo`).

Primary documentation rechecked: **2026-10-15**.

## Source-by-source capability matrix

| Surface | Eligible user / use (documented) | Geography / date coverage | API vs product distinction | Access requirements | Available fields (high level) | Known unknowns | MarketOS MX commercial product-attention |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Research API (Research Tools) | Independent academic / non-commercial researchers; FAQ: creator/advertiser/**commercial user → No** | Applicant regions on products page: U.S., Europe, Canada, Brazil (Mexico **not** listed). Video `region_code` enum includes `MX` as creator registration country—not applicant eligibility | Research Tools query API for public videos/accounts; separate from CCL, Creative Center, Marketing API | Approved research project + research client; Research Tools ToS; quotas (e.g. 1000 req/day, up to 100k records/day for approved research) | Public account/content fields per codebook / Query Videos | Exact Mexico researcher-expansion timing; whether any non-FAQ commercial path exists (none documented) | **Blocked / unavailable.** Commercial FAQ No; applicant regions exclude Mexico; no live transport |
| Commercial Content API | Products page: “public and researchers”; requester may be in any country while data phase is EU-only. **Do not assume** the Research API academic eligibility rule applies verbatim—no dedicated CCL eligibility FAQ found (doc URL 404) | Supported Countries: EU, EEA, UK, CH. Products page: EU ads “to begin with.” **Mexico not listed** | Ad-library / Commercial Content Library APIs under Research & Insights; distinct product from Research API video query | Application + approved client key; Getting Started uses research client + OAuth client token | Ads, advertiser metadata, targeting, reach-style fields (Query Ads / Advertisers / reports) | Whether CCL has a commercial-use exception separate from Research Tools FAQ; future non-EU expansion timeline | **Unavailable for MX attention.** Even setting eligibility aside, documented ad geography excludes Mexico; no live transport |
| Creative Center | Public website; login optional for more features | Website visibility; not an ingest geography contract | Inspiration / Top Ads / Trends **website**; Symphony tools are creative production—not Research Tools | Browser access; optional login. **Not** an API ingest license for MarketOS | Trends/Top Ads UI (not a MarketOS-normalized ingest schema here) | Whether any future official readonly ingest API will exist | **No supported ingest.** Visibility ≠ scrape/API permission |
| Marketing API (TikTok for Business) | Advertisers / partners operating owned ad accounts | Own-account campaigns; not market-wide public demand geography | Business Marketing API for campaign create/report—not Research Tools attention | Advertiser credentials / Business Center | Own-account analytics and mutation-adjacent campaign objects | Portal docs are SPA-heavy; field catalogs not fully extracted in this offline audit | **Not market-wide attention.** Own-account metrics must not be labeled competitor/demand proof; out of this layer’s scope |

### Citations (primary, accessed 2026-10-15)

- [Research Tools product page](https://developers.tiktok.com/products/research-api/) — researcher regions; non-commercial / independent-of-commercial-interests criteria.
- [Research API FAQ](https://developers.tiktok.com/doc/research-api-faq) — “I am a creator, advertiser, or commercial user… Am I eligible…? **No.**”; country eligibility deferred to products page.
- [Getting Started - Research API](https://developers.tiktok.com/doc/research-api-get-started) — research client + bearer flow.
- [Query Videos](https://developers.tiktok.com/doc/research-api-specs-query-videos) — `region_code` includes `MX` (creator registration), not MarketOS coverage.
- [Commercial Content API product page](https://developers.tiktok.com/products/commercial-content-api) — public/researchers; EU ads phase; requester any country.
- [Getting Started - Commercial Content API](https://developers.tiktok.com/doc/commercial-content-api-getting-started) — research client under Research & Insights.
- [Supported Countries (CCL)](https://developers.tiktok.com/doc/commercial-content-api-supported-countries) — EU / EEA / UK / CH; Mexico absent.
- [Creative Center help](https://ads.tiktok.com/help/article/creative-center) — public inspiration hub.
- [TikTok API for Business portal](https://business-api.tiktok.com/portal/docs) — Marketing API advertiser surface.

## What ordinary runtime does

1. Status: `blocked_ineligible_commercial_use` (or related blocked statuses).
2. `evidence_count = 0`, `operational_capability = false`, `eligible_live_source = null`.
3. Surfaces matrix evaluates Research API, CCL, Creative Center, and Marketing API
   separately; CCL notes explicitly refuse an assumed identical Research API
   eligibility rule and mark Mexico unsupported for ad geography.
4. Live requests (`allow_live` / `SidecarContext(dry_run=False)`) → `blocked_live_mode`.

Offline demo modes (`fixture_demo`, `manual_import`, `fake_transport`) require
explicit `allow_offline_demo=True` / `--allow-offline-demo`. They normalize
through `ConsumerAttentionEvidence` for tests only and never become observed/live.

## Run it

```text
# Ordinary capability report (zero rows; blocked)
python scripts/run_tiktok_research_evidence.py --json

# Explicit offline demo only (not operational)
python scripts/run_tiktok_research_evidence.py --mode fixture_demo --allow-offline-demo --markdown
python scripts/run_tiktok_research_evidence.py --mode fake_transport --allow-offline-demo --json
python scripts/run_tiktok_research_evidence.py --allow-live --json
```

Bridge:

```text
from backend.adapters.research.tiktok_research_evidence import fetch_research_evidence
from backend.contracts.adapters import SidecarContext

evidence = fetch_research_evidence("mini thermal printer", context=SidecarContext(dry_run=True))
assert evidence.evidence_count == 0
assert evidence.operational_capability is False
```

## Canonical dependencies (not invented here)

- Approval Ledger `provider_call` remains blocked in the offline ledger; this
  module does not mint approvals or treat booleans as authorization.
- Live secret resolution is not invoked because no eligible live transport exists.
- Do not add a second credential/approval system in this lane.

## Vertical composition

Path-disjoint from PR #459 (legacy client retirement) and PR #468 (TikTok route
approval gate). Does not modify `backend/adapters/tiktok_organic.py`. Composition
regressions: `tests/test_tiktok_vertical_composition.py`.

## Future activation (only if eligibility and geography change)

1. TikTok primary docs must expressly permit MarketOS commercial use **and**
   document Mexico (or target-market) coverage for the chosen surface.
2. Do not invent a live transport solely to appear operational.
3. Approval Ledger `provider_call` with evidence.
4. Metadata-only credential reference.
5. Separately reviewed live transport + output contract + privacy review.
6. Keep attention supplemental; never promote to purchase/supplier proof; never
   relabel Marketing API own-account metrics as market demand.
