# Cross-Source Live Capability Conformance

Status: **contract-tested, offline only**. This document and
`tests/contracts/test_cross_source_live_capability_conformance.py` are a
cross-source regression artifact, not a runtime provider registry, scorer,
approval authority, credential store, or evidence database. Adapter modules,
the CompanyOS Approval Ledger, workspace controls, and canonical evidence
consumers remain the authorities.

Accessed: 2026-10-14 (UTC). The seven source PRs below were inspected at the
immutable heads listed in the handoff. They are open branches, not mainline
production dependencies. A source being listed here does not mean that its
live transport is enabled or eligible for MarketOS.

## Matrix

| Source / PR | Evidence meaning | Scope | Current safe status | Live prerequisite boundary | Prohibited inference |
| --- | --- | --- | --- | --- | --- |
| eBay Browse / #479 | Public marketplace listing, price, shipping, and availability observation | Public marketplace listing | Blocked pending authorization and credential-reference review | Approval Ledger provider-call decision, metadata-only credential reference, bounded live transport, output contract | Supplier proof, sales, launch authorization |
| Google Trends / #480 | Relative search interest normalized to time and geography | Public market-wide signal | Fixture/dry-run only; endpoint/auth details remain unverified | Official method/access confirmation, explicit geography/language, approved read transport | Absolute volume, sales, purchase intent, supplier proof |
| Meta Ad Library / #489 | Advertiser-transparency records supplied by the operator | Public advertiser transparency | Fixture-only and not an authenticated observation | Official scope/access confirmation and bounded read transport | Market demand, ad performance, sales, launch authorization |
| Amazon Bestsellers / #493 | Relative bestseller rank when explicitly supplied | Public marketplace rank | Unavailable live; explicit fixtures only | Amazon-documented eligible capability, authorized scope, reviewed transport | Unit sales, profit, supplier proof, launch authorization |
| TikTok Research / #494 | Public research-tool content/account observations where eligible | Public content research | Blocked for current commercial/Mexico use | Eligibility/geography confirmation, approved research client, reviewed transport | Market demand, supplier proof, ad spend, launch authorization |
| Meta Insights / #508 | Account-scoped ad delivery/performance metrics | Authorized advertiser account | Blocked; never a market-wide signal | Account authorization, credential reference, Approval Ledger, bounded read transport | Market-wide demand, competitor intelligence, verified sales, launch |
| Google Ads Keyword Planning / #509 | Historical keyword-planning metrics for explicit targeting | Account-scoped planning | Blocked; live transport not implemented | Ads account/project authorization, explicit geography/language/network, approved transport | Sales, supplier proof, live campaign performance, launch |

The current mainline also contains older adapter surfaces. They are not
silently promoted by this matrix. In particular, `DataForSEO` has a tested
offline boundary and returns a structured blocked result for live-mode input;
the public RSS policy requires explicit network opt-in. Any adapter that does
not emit the required provenance/status fields remains an owner-ready contract
gap rather than an implicit conformance pass.

## Required observable contract

Every adapter result that crosses into a shared research consumer must retain,
without inference or defaulting:

- source identity and adapter method;
- candidate/query identity;
- evidence class and provenance;
- collection/observation time and freshness state;
- geography and language, when the source exposes them;
- currency and amount units, or explicit unavailable state;
- account/workspace identity where the source is account-scoped;
- bounded records, warnings, status, and error class;
- whether network was used, credentials were loaded, and live validation occurred.

`fixture`, `manual_import`, `blocked`, `unavailable`, and fake-transport
results cannot set `live_validated=true`. A live request that fails, is denied,
or returns an empty result must not be replaced with fixture/demo records.
Missing values remain missing; explicit zero remains an observed zero. No
adapter result may turn relative interest into volume, ad spend into demand,
account analytics into market-wide evidence, rank into unit sales, or any
source signal into supplier proof, compliance clearance, promotion, launch,
advertising, payment, order, or publishing authority.

The conformance test intentionally validates these properties with synthetic
outcomes and existing offline authorities. It does not call providers, read
credentials, or make live requests.

## Capability and approval boundary

The existing `backend.discovery.registry.DiscoveryRegistry` and
`backend.contracts.adapters.AdapterHealth` are descriptive/runtime health
surfaces. This artifact does not add metadata to them or create a second
registry. Source eligibility is not inferred from a registry entry, a boolean
`allow_network`, a non-empty fixture, or a successful parser test.

Account-scoped sources require a server-side credential reference and
workspace/owner authorization before any future read. Secret values, tokens,
cookies, raw provider payloads, and account identifiers are not accepted by
this contract. The Approval Ledger and TrustOS controls remain the only
approval/export authorities.

## Primary documentation

These links support source meaning and access constraints; they do not grant
MarketOS permission to activate a provider:

- [eBay Browse API](https://developer.ebay.com/develop/api/buy/browse_api) — Browse search requires an application access token.
- [Google Trends data FAQ](https://support.google.com/trends/answer/4365533) — Trends is normalized relative interest on a 0–100 scale, not absolute volume.
- [Meta Ad Library API](https://www.facebook.com/ads/library/api/) — documented archive scope and API authorization requirements.
- [Amazon SP-API onboarding](https://developer-docs.amazon.com/sp-api/docs/onboarding-overview) — seller authorization, application registration, and role requirements.
- [TikTok Research API](https://developers.tiktok.com/doc/research-api-get-started/) — approved research client and access token requirements for public research data.
- [Meta Marketing API Insights](https://developers.facebook.com/docs/marketing-api/insights/) — account-scoped insights surface; live access is not enabled by this artifact.
- [Google Ads keyword planning](https://developers.google.com/google-ads/api/docs/keyword-planning/overview) — historical metrics and planning operations, not sales proof.

## Ownership and rollout

The seven adapter PRs remain separate source owners. If one adapter violates
this contract, the required fix belongs in that adapter's branch and tests;
this artifact must not absorb adapter implementation or create a parallel
transport. A future live-read PR must pin its official capability evidence,
obtain explicit Approval Ledger/credential/workspace gates, preserve the
normalized fields above, and add a direct conformance case before it can be
described as live.
