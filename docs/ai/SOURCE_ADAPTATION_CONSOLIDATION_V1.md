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
| --- | ---: | --- | --- | ---: | --- | --- |
| `data/source_adaptation_registry.json` | 54,393 | `4b7b0dbe2c41834db575fc26ee1d3b603cfddc34` | 29 | `af801a6fe28676c26f6199cf08b8c7b53032ca588e8865a1f6bc96367ee6714a` | `08cd9984bd7071411be15aae6c11093d2de2337ba6f0c04d0e079738cef88242` | `2be9683dec56e233f7feb6188e069438f8a11a9830db902f45c75b08e4e03793` |
| `data/source_adaptation_work_orders.json` | 59,536 | `9cbef45172703a0518e1013058f9ed4c98841a96` | 29 | `14374a79338cce19f114dd6b2c9b5a3ef2276783da48768eb4d67a08bf301d19` | `daaaccfe41fa461273bf75f0206d818ec308c3b76a5216d39b066d8d3baeed84` | work-order registry stable hash `585cbdd2286e087c27ac2a3bfa1b29d59e35474d342a0946de4ecc4f6fc950ee` |

Do not conflate these:

- **Raw SHA-256** hashes the exact tracked bytes (pretty-printed JSON + trailing newline).
- **Canonical sorted-key SHA-256** hashes `json.dumps(obj, sort_keys=True, separators=(",", ":"))`.
- **Stable content hash** is `SourceAdaptationRegistry.compute_stable_hash()` (`sort_keys=True, indent=2`).

Superseded claims (not the tracked blobs):

- PR-body / prior doc sizes `55,544` / `61,094` with raw SHA-256 `0de36a93…` / `4349bde0…` do **not** match `HEAD:data/source_adaptation_*.json`.
- Earlier draft sizes `54,227` with raw `56b7076c…` were a truncated payload in commit `7248a8ab` and were recovered.

The checked-out branch contains the fully restored 29-record catalog and 29 matching work orders (`src-<id>` -> `wo-<id>`), with stable content hash `2be9683d…` matching `tests/contracts/test_source_adaptation_governance.py`.

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
| Temporal (`src-temporal`) | `9fde38c0cd1f437774ba48da695bcdfb88c242e1` confirmed; tag `v1.8.0` matches | declared `1.8.0` | **LICENSE at pin is MIT**; corrected in registry. Rejection maintained fail-closed on architecture grounds (single event spine invariant). | verified (rejected fail-closed on architecture grounds) |
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
