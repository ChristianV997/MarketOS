# Source-adaptation consolidation v1

Lane: `SOURCE-ADAPTATION-CANONICAL-REGISTRY-V2` / PR #272. Draft only. Do not merge.

Corrections are applied to the canonical files:

- `data/source_adaptation_registry.json`
- `data/source_adaptation_work_orders.json`
- `evaluation/source_governance/validator.py` (calls `consolidation_rules.extra_record_errors`)

There is no overlay authority. `data/source_adaptation_corrections_v1.json` is removed.

## Canonical Payload & Hash Audit

The canonical builder `scripts/ai/build_source_adaptation_registry.py` is the single source of truth for both the registry and adaptation work orders. Executing the builder produces bit-for-bit identical outputs:

| File | Size (bytes) | Records | Raw SHA256 | Canonical Sorted-Key SHA256 | Stable Content Hash |
| --- | ---: | ---: | --- | --- | --- |
| `data/source_adaptation_registry.json` | 55,544 | 29 | `0de36a93d64ad9cbbb2427159792a83da9ee18cdc5a9890d05dff1b62e5cac9b` | `1e0db9350cc50ef9965ed97163bc5b9a7070ee816c853da3790ffa4ac2f21981` | `faf789e185374adb6cfe167b8bb85fcdd55afb6597d00ab943f405899fce8c56` |
| `data/source_adaptation_work_orders.json` | 61,094 | 29 | `4349bde089a25a8379bba4b4804f8a7496a23eb1da51324f93880b0e6785ea0e` | `7fff93c3bcf604dcf3505ed33fb6db16ea75e8a8783a1ffa909d78ab0936a0f2` | N/A (per-order hashes) |

Note on earlier claims: Earlier draft PR descriptions cited temporary artifact hashes (`54,227 bytes`, raw `56b7076c...`, sorted `c70b723d...`) from a transient broken-payload state in commit `7248a8ab`. The actual checked-out branch contains the fully restored 29-record catalog and 29 matching work orders (`src-<id>` -> `wo-<id>`), with stable content hash `faf789e1...` matching the golden contract test in `tests/contracts/test_source_adaptation_governance.py`.

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

Registry validation checks SHA syntax offline; that is not proof that a Git object exists. A focused read-only verification checked all records against primary upstream GitHub refs, tags, and license files:

| Source | Exact commit | Declared tag | License at pinned commit | Result |
| --- | --- | --- | --- | --- |
| Crawl4AI (`src-crawl4ai`) | GitHub commit lookup returned 422; commit page returned 404 | `v0.4.2` ref returned 404 | Apache-2.0 confirmed upstream | blocked / unresolved pin |
| Hermes (`src-hermes-ecc`) | `027d1a8a6043355b7af53b4c0645336b41372b7b` resolves in `NousResearch/hermes-agent` | `v1.2.0` ref returned 404 | MIT confirmed at the exact commit | partial; tag unresolved |
| Higgsfield CLI (`src-higgsfield-cli`) | `dc7e2d274bf7aa112ce8d76a085b3bc91aa08415` confirmed on `higgsfield-ai/cli` | `v0.3.1` tag does not match commit (`dc7e2d2` belongs to `v1.1.25`) | MIT confirmed at the exact commit | partial; tag mismatch |
| Higgsfield GPU (`src-higgsfield-gpu-orchestration`) | `9576d37618c028f992cb42307e33292da1220407` confirmed on `higgsfield-ai/higgsfield` | `v0.0.4-rc` points to exact commit | Apache-2.0 confirmed at the exact commit | verified (rejected fail-closed) |
| Higgsfield Python SDK (`src-higgsfield-python-sdk`) | GitHub commit lookup returned 422; commit page returned 404 | `0.1.0` is PyPI package version; repo has no git tags | Apache-2.0 confirmed upstream | blocked / unresolved pin |
| Higgsfield Skills (`src-higgsfield-skills`) | GitHub commit lookup returned 422; commit page returned 404 | `0.12.0` is in-tree `VERSION` file, not a git tag | MIT confirmed upstream | blocked / unpinned tag |
| Prefect (`src-prefect`) | `c8986edebb2dde3e2a931adbe24d2eaefcb799cb` resolves in `PrefectHQ/prefect` | `3.2.0` points to the exact commit | Apache-2.0 confirmed at the exact commit | verified (rejected fail-closed) |
| gstack (`src-gstack`) | `a6b3a57512ca6d5c6aa5b68f74f736195021f96e` resolves in `garrytan/gstack` | `main-pinned` (PR #2882) | MIT confirmed at the exact commit | verified (reference_only) |
| Temporal (`src-temporal`) | `9fde38c0cd1f437774ba48da695bcdfb88c242e1` resolves in `temporalio/temporal` | `1.8.0` | Upstream is MIT (not BSL-1.1); rejection mandatory via architecture invariant | architectural rejection preserved |

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
