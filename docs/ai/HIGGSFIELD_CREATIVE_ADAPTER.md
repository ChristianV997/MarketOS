# Higgsfield creative-provider adapter

Offline, dry-run-first MarketOS port. It does not generate media, install
the Higgsfield CLI/SDK, register an MCP server, or authorize publication.

## Sources inspected

| Repository | Commit / tag | License | Adopted | Rejected |
| --- | --- | --- | --- | --- |
| higgsfield-ai/skills | public main / VERSION 0.12.0 | MIT | Workflow names only | Skill install, CLI auth, hidden prompts |
| higgsfield-ai/cli | `dc7e2d2` / v1.1.25 | MIT | Job/status/cost grouping | `auth login`, generate, website deploy |
| higgsfield-ai/higgsfield-client | 0.1.0 | Apache-2.0 | Timeout/unavailable taxonomy | `subscribe`/`submit`, `HF_KEY` |
| higgsfield-ai/higgsfield-js | npm 0.2.6 | MIT | Server-only boundary | Browser SDK |
| higgsfield-ai/cursor-plugin | plugin 1.1.0 | MIT | Tool grouping reference | MCP registration |
| higgsfield-ai/fnf-local-pluging-bridge-mcp | public main | MIT | None | Desktop AE/Blender control |
| higgsfield-ai/higgsfield | `v0.0.4-rc` | Apache-2.0 | None | GPU orchestration |

## Commercial draft workflow

`evaluation.creative.workflow` binds creative jobs to product/offer/SKU,
supplier offer, market lane, workspace, language/locale, brief type,
claims, evidence, approval, asset lineage, and replay hash.

Named drafts: hydroponics Spanish-first education, smart-pet support-risk,
solar 4G security blocked on missing compliance/SIM/support, marketplace
card with exact SKU, product-validation appendix, managed-acquisition
variants (en-US + en-CA).

Creative quality is `draft_only`. Commercial validation is
`not_commercially_validated`. Client export requires evidence ids and
`approval_state=approved`.

## Source governance

Consumes PR #257 by reference only:
`MarketOS.SourceGovernance.Higgsfield.v1-pending`.
Do not fork the registry.

## Modes

`fixture`, `manual_import`, `dry_run`, `blocked_live`, `live_unavailable`.

## Rollback

Delete `evaluation/creative/`, `tests/creative/`, and this file.
