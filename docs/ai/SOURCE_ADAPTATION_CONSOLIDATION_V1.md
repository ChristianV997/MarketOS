# Source-adaptation consolidation v1

Lane: `SOURCE-ADAPTATION-CANONICAL-REGISTRY-V2` / PR #272. Draft only. Do not merge.

Corrections are applied to the canonical files:

- `data/source_adaptation_registry.json`
- `data/source_adaptation_work_orders.json`
- `evaluation/source_governance/validator.py` (calls `consolidation_rules.extra_record_errors`)

There is no overlay authority. `data/source_adaptation_corrections_v1.json` is removed.

## Canonical Payload & Hash Audit

Hashes below are from the tracked git blobs in an exclusive checkout of
`grok/marketos-source-adaptation-consolidation-v1`, measured with SHA-256 of
raw file bytes and `git cat-file -s` / `git rev-parse HEAD:<path>`. PR-body
hashes and artifact copies are not authority.

The canonical builder `scripts/ai/build_source_adaptation_registry.py` is the
single source of truth. Executing the builder against this branch is
bit-for-bit identical to the tracked files.

| File | Size (bytes) | Git blob SHA | Records | Raw SHA256 | Canonical Sorted-Key SHA256 | Stable Content Hash |
| --- | ---: | --- | ---: | --- | --- | --- |
| `data/source_adaptation_registry.json` | 54,269 | `1249d925d310d24b28e5be56ac9e8d95e98a63f3` | 29 | `a248b83b28189143096d4c32213e4b3a297e4981c0185f7bdb559c6b64c12647` | `1e0db9350cc50ef9965ed97163bc5b9a7070ee816c853da3790ffa4ac2f21981` | `faf789e185374adb6cfe167b8bb85fcdd55afb6597d00ab943f405899fce8c56` |
| `data/source_adaptation_work_orders.json` | 59,535 | `10a0545a9e30683630b32d89030bed9a9cd32753` | 29 | `b62badaed1c09691a56e8f4d2fc0274d0823e2024500fe271cb577f1f1f9abdf` | `7fff93c3bcf604dcf3505ed33fb6db16ea75e8a8783a1ffa909d78ab0936a0f2` | work-order registry stable hash `ebfa075870f2c5a8d3b29c67b45970708e736cb26fb3f4f7b80a8e7a65dd56fd` |

Do not conflate these:

- **Raw SHA-256** hashes the exact tracked bytes (pretty-printed JSON + trailing newline).
- **Canonical sorted-key SHA-256** hashes `json.dumps(obj, sort_keys=True, separators=(",", ":"))`.
- **Stable content hash** is `SourceAdaptationRegistry.compute_stable_hash()` (`sort_keys=True, indent=2`).

Superseded claims (not the tracked blobs):

- PR-body / prior doc sizes `55,544` / `61,094` with raw SHA-256 `0de36a93…` / `4349bde0…` do **not** match `HEAD:data/source_adaptation_*.json`.
- Earlier draft sizes `54,227` with raw `56b7076c…` were a truncated payload in commit `7248a8ab` and were recovered.

The checked-out branch contains the fully restored 29-record catalog and 29 matching work orders (`src-<id>` -> `wo-<id>`), with stable content hash `faf789e1…` matching `tests/contracts/test_source_adaptation_governance.py`.

## Applied pins

| Source | Mode | Revision | Target |
| --- | --- | --- | --- |
| Crawl4AI | integrate | `b04ed9f3a941a96509272f3bc14be85f5767736a` (blocked / unverified pin) | `backend.adapters.research.crawl4ai` |
| Higgsfield GPU | reject | `9576d37618c028f992cb42307e33292da1220407` (`v0.0.4-rc` confirmed) | none |
| Higgsfield CLI | reference_only | `dc7e2d274bf7aa112ce8d76a085b3bc91aa08415` (`v1.1.25` commit; `v0.3.1` tag unresolved) | docs.ai.standards |
| CoderOS | reference_only | `b980e90b49ea7c0639094f3060ced5aaf772a571` | docs.ai.standards |
| gstack | reference_only | `a6b3a57512ca6d5c6aa5b68f74f736195021f96e` (PR #2882 verified) | docs.ai.standards |
| Hermes | reference_only | NousResearch/hermes-agent `027d1a8a6043355b7af53b4c0645336b41372b7b` | docs.ai.standards |

## Immutable Pin & Upstream Verification Audit

Registry validation checks SHA syntax offline; that is not proof that a Git
object exists. Re-verified 2026-09-20 against primary GitHub commit, tag, and
license endpoints (not pretty-printed connector JSON):

| Source | Exact commit | Declared tag | License at pin / GitHub SPDX | Result |
| --- | --- | --- | --- | --- |
| Crawl4AI (`src-crawl4ai`) | GitHub commit lookup 422; SHA `b04ed9f3…` not on `unclecode/crawl4ai` | `v0.4.2` ref not found (repo tags are `v0.7+`) | Apache-2.0 confirmed on default branch | **unresolved pin** (kept; do not retarget to HEAD) |
| Hermes (`src-hermes-ecc`) | `027d1a8a6043355b7af53b4c0645336b41372b7b` resolves in `NousResearch/hermes-agent` | `v1.2.0` not present (upstream uses `v2026.x.y`) | MIT confirmed | **partial**; tag unresolved |
| Higgsfield CLI (`src-higgsfield-cli`) | SHA `dc7e2d27…` 422 on `higgsfield-ai/cli` | `v0.3.1` not among listed tags | MIT on default branch | **unresolved pin** (kept) |
| Higgsfield GPU (`src-higgsfield-gpu-orchestration`) | `9576d37618c028f992cb42307e33292da1220407` confirmed | `v0.0.4-rc` matches commit | Apache-2.0 confirmed | verified (rejected fail-closed) |
| Higgsfield Python SDK (`src-higgsfield-python-sdk`) | SHA `aefd1ca4…` 422 on `higgsfield-ai/higgsfield-client` | `0.1.0` not a git tag | Apache-2.0 on default branch | **unresolved pin** (kept) |
| Higgsfield Skills (`src-higgsfield-skills`) | SHA `d0714066…` 422 on `higgsfield-ai/skills` | `0.12.0` not a git tag | MIT on default branch | **unresolved pin** (kept) |
| Higgsfield TS SDK (`src-higgsfield-ts-sdk`) | `e3f274249962417e21f6566d4eecec6d8491d11c` confirmed; tag `0.2.6` matches | `0.2.6` | GitHub license API 404; declared MIT unverified at pin | **partial**; license unresolved |
| Prefect (`src-prefect`) | `c8986edebb2dde3e2a931adbe24d2eaefcb799cb` confirmed | `3.2.0` matches | Apache-2.0 confirmed | verified (rejected fail-closed) |
| gstack (`src-gstack`) | `a6b3a57512ca6d5c6aa5b68f74f736195021f96e` confirmed | `main-pinned` | MIT confirmed | verified (reference_only) |
| Temporal (`src-temporal`) | `9fde38c0cd1f437774ba48da695bcdfb88c242e1` confirmed; tag `v1.8.0` matches | declared `1.8.0` | **LICENSE at pin is MIT**, registry still says `BSL-1.1` | **license field unresolved/incorrect**; rejection kept via event-spine invariant |
| CoderOS (`src-coderos`) | `b980e90b49ea7c0639094f3060ced5aaf772a571` confirmed | `frozen-control-plane` | GitHub SPDX MIT; registry `Proprietary-Internal` (internal classification) | commit verified; license classification policy, not retargeted |
| Remaining 18 sources (airbyte, chatwoot, dagster, dlt, duckdb, firecrawl, great-expectations, higgsfield-mcp-bridge, medusa, n8n, opa, openlineage, otel-python, polars, pyperf, saleor, scrapy, vendure) | pinned commit resolves and declared tag matches (or intentional `main-pinned`) | see registry | SPDX or LICENSE file present; ELv2/AGPL/Sustainable Use recorded as `NOASSERTION`/`Other` on GitHub but fail-closed reject already applied | verified |

Unresolved items are left in place. Do not replace them with moving branch heads merely to satisfy validation. Resolve exact reviewed revisions through authoritative refs, update the canonical generator and generated work orders together, and rerun source-governance contracts before treating this draft as merger-ready.


## Architectural Invariants & Policy Enforcement

- **Single Event Spine & Incompatible Architecture**:
  - `src-temporal` is rejected because a duplicate external workflow orchestrator runtime, worker daemon pool, and secondary persistence requirements violate MarketOS's single canonical event spine invariant (`backend.events.spine`).
  - `src-prefect` is rejected for equivalent workflow engine duplication.
- **Copyleft & Non-Commercial License Denials**:
  - AGPL-3.0 (`src-chatwoot`, `src-firecrawl`), ELv2 (`src-airbyte`), and Sustainable Use (`src-n8n`) are rejected fail-closed to prevent viral copyleft or commercial restrictions from infecting MarketOS.
- **Desktop Control & Hardware Bridges**:
  - `src-higgsfield-mcp-bridge` is rejected fail-closed due to local desktop control automation and unverified OS IPC bridges.
  - `src-higgsfield-gpu-orchestration` is rejected fail-closed due to unapproved GPU daemon dependencies.

Do not replace unresolved pins with moving branch heads merely to satisfy validation. Resolve exact reviewed revisions through authoritative refs, update the canonical generator and generated work orders together, and rerun source-governance contracts before treating this draft as merger-ready.

Rollback: revert PR #272. No live providers, no GPU/desktop runtime, no second registry.
