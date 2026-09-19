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

## Commit-object verification

Registry validation checks SHA syntax offline; that is not proof that a Git object exists. A read-only GitHub commit/tag-reference check on 2026-09-18 resolved 23 of 29 catalog pins. The following six remain unverified and block source-governance acceptance:

- Crawl4AI (`src-crawl4ai`)
- Hermes (`src-hermes-ecc`)
- Higgsfield CLI (`src-higgsfield-cli`)
- Higgsfield Python SDK (`src-higgsfield-python-sdk`)
- Higgsfield Skills (`src-higgsfield-skills`)
- Prefect (`src-prefect`)

Do not replace these pins with moving branch heads merely to satisfy validation. Resolve the exact reviewed revisions, update the canonical generator and its generated work orders together, and rerun the source-governance contracts before treating this draft as merger-ready.

Rollback: revert PR #272. No live providers, no GPU/desktop runtime, no second registry.
