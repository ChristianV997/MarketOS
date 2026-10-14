# TikTok Research Evidence (commercial-attention capability)

Default-off capability contract for TikTok consumer-attention / creative
evidence. It does **not** call TikTok, load credentials, scrape Creative
Center, or authorize ads, spend, messaging, or publishing.

**Operational result under current official terms:** MarketOS has **no eligible
official live source** for commercial product/competitor attention research on
TikTok. Ordinary runtime returns zero evidence rows with a precise blocked
status. Offline fixtures/fakes are test/demo only (`allow_offline_demo`).

Primary documentation rechecked: **2026-10-14**.

## Source-by-source eligibility

| Surface | Documented role | Auth / geography / quotas | MarketOS commercial attention use |
| --- | --- | --- | --- |
| Research API | Query public videos/accounts under Research Tools | Approved research project + research client; regional eligibility for researchers; approved-project quotas (e.g. 1000 req/day, up to 100k records/day) | **Not eligible.** FAQ: creators, advertisers, commercial users → **No.** Academic eligibility ≠ MarketOS commercial authorization |
| Commercial Content API | Query public ad-library-style data under Research Tools | Same Research Tools approval/client model | **Not eligible** under the same FAQ (Research Tools) |
| Creative Center | Public website for trends/ad inspiration; login optional for more features; Symphony API is creative production | Website access ≠ API ingest contract | **No supported MarketOS ingest.** Visibility is **not** scrape permission |
| Marketing API (TikTok for Business) | Advertiser-account campaign creation/reporting | Advertiser credentials; own-account analytics | **Not market-wide attention evidence.** Own-account performance must not be labeled competitor/demand proof; mutation-adjacent and out of this layer’s scope |

### Citations (primary)

- [Research API FAQ](https://developers.tiktok.com/doc/research-api-faq) — “I am a creator, advertiser, or commercial user… Am I eligible…? **No.**”; application + approved project required; quotas for approved research (accessed 2026-10-14).
- [Getting Started - Research API](https://developers.tiktok.com/doc/research-api-get-started) — research client + bearer flow (accessed 2026-10-14).
- [Getting Started - Commercial Content API](https://developers.tiktok.com/doc/commercial-content-api-getting-started) — Research Tools adlib path (accessed 2026-10-14).
- [Developer docs overview](https://developers.tiktok.com/doc/overview) — Research Tools vs Creative Center (accessed 2026-10-14).
- [Creative Center help](https://ads.tiktok.com/help/article/creative-center) — public inspiration hub (accessed 2026-10-14).
- [TikTok API for Business portal](https://business-api.tiktok.com/portal/docs) — Marketing API advertiser surface (accessed 2026-10-14).

## What ordinary runtime does

1. Status: `blocked_ineligible_commercial_use` (or related blocked statuses).
2. `evidence_count = 0`, `operational_capability = false`, `eligible_live_source = null`.
3. Surfaces matrix marks Research Tools commercial-ineligible and Creative Center /
   Marketing API as unsupported for this use case.
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

## Future activation (only if eligibility changes)

1. TikTok FAQ/terms must expressly permit commercial MarketOS use (today: No).
2. Approval Ledger `provider_call` with evidence.
3. Metadata-only credential reference.
4. Separately reviewed live transport + output contract + privacy review.
5. Keep attention supplemental; never promote to purchase/supplier proof; never
   relabel Marketing API own-account metrics as market demand.
