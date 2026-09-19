# Source-adaptation consolidation v1

Lane: `SOURCE-ADAPTATION-CANONICAL-REGISTRY-V2` / PR #272. Draft only. Do not merge.

Corrections are applied to the canonical files:

- `data/source_adaptation_registry.json`
- `data/source_adaptation_work_orders.json`
- `evaluation/source_governance/validator.py` (calls `consolidation_rules.extra_record_errors`)

There is no overlay authority. `data/source_adaptation_corrections_v1.json` is removed.

## Applied pins

| Source | Mode | Revision | Target |
| --- | --- | --- | --- |
| Crawl4AI | integrate | `b04ed9f3a941a96509272f3bc14be85f5767736a` | `backend.adapters.research.crawl4ai` |
| Higgsfield GPU | reject | `f412895ea91054ee839f506bd419ec87fa094183` | none |
| Higgsfield CLI | reference_only | `dc7e2d274bf7aa112ce8d76a085b3bc91aa08415` / v1.1.25 | docs.ai.standards |
| CoderOS | reference_only | `b980e90b49ea7c0639094f3060ced5aaf772a571` | docs.ai.standards |
| gstack | reference_only | `a6b3a57512ca6d5c6aa5b68f74f736195021f96e` | docs.ai.standards |
| Hermes | reference_only | NousResearch/hermes-agent `027d1a8a6043355b7af53b4c0645336b41372b7b` | docs.ai.standards |

## Immutable Pin Verification

Registry validation checks SHA syntax offline; that is not proof that a Git object exists. The earlier catalog sweep recorded 23 of 29 commit objects as resolved. A focused read-only follow-up on 2026-09-19 checked each of the six previously unresolved source records against GitHub commit/tag refs and the license file at the exact commit where available:

| Source | Exact commit | Declared tag | License at pinned commit | Result |
| --- | --- | --- | --- | --- |
| Crawl4AI (`src-crawl4ai`) | GitHub commit lookup returned 422; commit page returned 404 | `v0.4.2` ref returned 404 | unavailable without a resolvable commit | unresolved |
| Hermes (`src-hermes-ecc`) | `027d1a8a6043355b7af53b4c0645336b41372b7b` resolves in `NousResearch/hermes-agent` | `v1.2.0` ref returned 404 | MIT confirmed at the exact commit | partial; declared version tag unresolved |
| Higgsfield CLI (`src-higgsfield-cli`) | commit lookup/page did not resolve | `v0.3.1` ref returned 404 | unavailable without a resolvable commit | unresolved |
| Higgsfield Python SDK (`src-higgsfield-python-sdk`) | GitHub commit lookup returned 422; commit page returned 404 | `0.1.0` ref returned 404 | unavailable without a resolvable commit | unresolved |
| Higgsfield Skills (`src-higgsfield-skills`) | GitHub commit lookup returned 422; commit page returned 404 | `0.12.0` ref returned 404 | unavailable without a resolvable commit | unresolved |
| Prefect (`src-prefect`) | `c8986edebb2dde3e2a931adbe24d2eaefcb799cb` resolves in `PrefectHQ/prefect` | `3.2.0` points to the exact commit | Apache-2.0 confirmed at the exact commit | verified |

The Hermes and Prefect license evidence URLs in the canonical builder now point to the immutable commit paths above; generated registry and work orders are rebuilt from that builder. Prefect is fully verified. Hermes' commit and license are verified, but its recorded `v1.2.0` tag is not; treat the Hermes record as unresolved until the version assertion is corrected from authoritative evidence. The other four source refs and their pinned licenses remain unavailable. Do not replace any revision with a moving branch head or infer a SHA. Keep PR #272 draft and blocked until all six records are fully resolved and focused contracts pass.

Do not replace unresolved pins with moving branch heads merely to satisfy validation. Resolve exact reviewed revisions through authoritative refs, update the canonical generator and generated work orders together, and rerun source-governance contracts before treating this draft as merger-ready.

Rollback: revert PR #272. No live providers, no GPU/desktop runtime, no second registry.
