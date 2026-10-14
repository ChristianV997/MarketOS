# TikTok Research Evidence (official Research Tools contract)

Offline / fixture / fake-transport contract for TikTok creative and ad
attention evidence. It does **not** call TikTok, load credentials, scrape
Creative Center, or authorize ads, spend, messaging, or publishing.

Access date for official documentation cited below: **2026-10-14**.

## Official capability findings

| Surface | Documented role | MarketOS commercial use |
| --- | --- | --- |
| Research API | Query videos/accounts under Research Tools; requires approved research project and research client credentials | **Not eligible.** FAQ: creators, advertisers, and commercial users are not eligible for Research Tools |
| Commercial Content API | Query public ad library-style data under Research Tools; same approval/client model | **Not eligible** for MarketOS commercial product research under the same FAQ |
| Marketing API (TikTok for Business) | Advertiser campaign/creative management | Out of scope here; would be spend/mutation-adjacent, not a default-off research evidence source |
| Creative Center | Public trend/inspiration website (login optional for more features); Symphony API is a separate creative-production surface | Website visibility is **not** permission to scrape; no official read-only research contract is implemented for commercial MarketOS use in this module |

### Citations (primary docs)

- [Getting Started - Research API](https://developers.tiktok.com/doc/research-api-get-started) — approved research client, bearer token, query examples (accessed 2026-10-14).
- [Research API FAQ](https://developers.tiktok.com/doc/research-api-faq) — eligibility application required; **“I am a creator, advertiser, or commercial user… Am I eligible…? No.”**; published daily quotas for approved research projects (accessed 2026-10-14).
- [Getting Started - Commercial Content API](https://developers.tiktok.com/doc/commercial-content-api-getting-started) — Research Tools adlib query flow (accessed 2026-10-14).
- [TikTok Developer Docs Overview](https://developers.tiktok.com/doc/overview) — Research API / Commercial Content API under Research & Insights; Creative Center listed separately (accessed 2026-10-14).

Academic Research API eligibility must not be treated as MarketOS commercial
authorization. This module therefore defaults to
`not_configured` / `blocked_ineligible_commercial_use` and never implements a
live Research Tools transport.

Published Research Tools quotas (approved projects only; not MarketOS live
authority): FAQ documents 1000 requests/day and up to 100,000 records/day across
APIs (reset 12:00 UTC), with separate follower-list caps. Those figures do not
unlock commercial MarketOS calls.

## What this module does

1. Reports honest capability status for Research API and Commercial Content API.
2. Accepts sanitized fixture / manual / fake-transport rows only.
3. Normalizes through
   `backend.adapters.research.consumer_attention.normalize_record` into
   `ConsumerAttentionEvidence`.
4. Scores only via `evaluation.commerce.consumer_attention.build_report`.
5. Keeps ad/creative attention distinct from purchase intent, sales, supplier
   proof, and product facts.
6. Rejects secret-shaped and raw-payload rows; unknown time/locale stays unknown.

It does **not** duplicate the generic consumer-attention CLI importer, and it
does **not** modify `backend.adapters.tiktok_organic` (signal mock / Creative
Center attempt path owned elsewhere).

## Run it

```text
python scripts/run_tiktok_research_evidence.py --json
python scripts/run_tiktok_research_evidence.py --mode fixture_demo --markdown
python scripts/run_tiktok_research_evidence.py --mode fake_transport --json
python scripts/run_tiktok_research_evidence.py --mode fake_transport --fake-error --json
python scripts/run_tiktok_research_evidence.py --allow-live --json
```

Default mode is `not_configured` (blocked capability package, zero evidence).
`--allow-live` is always fail-closed (`blocked_live_mode`).

Bridge entrypoint (product-research attachment shape):

```text
from backend.adapters.research.tiktok_research_evidence import fetch_research_evidence
from backend.contracts.adapters import SidecarContext

evidence = fetch_research_evidence(
    "mini thermal printer",
    context=SidecarContext(dry_run=True),
    mode="fixture_demo",
)
```

`SidecarContext(dry_run=False)` returns `blocked_live_mode` without loading
fixtures or opening a network path.

## Safety boundaries

No TikTok credentials, OAuth tokens, provider calls, unofficial libraries,
proxies, scraping, ad creation, spend, messaging, publishing, personal customer
profiles, or targeting attributes. Fixture/fake evidence is not live validation
or launch authorization. Client visibility remains `internal_only`.

## Future activation (only if eligibility changes)

1. Re-read TikTok Research Tools eligibility and terms; confirm commercial use
   is expressly permitted (today it is not).
2. Approval Ledger `provider_call` approval with evidence.
3. Metadata-only credential reference (no secret values in repo).
4. Separately reviewed live transport with network tests, output contract, and
   privacy review.
5. Keep attention evidence supplemental; never promote to purchase or supplier
   proof.
