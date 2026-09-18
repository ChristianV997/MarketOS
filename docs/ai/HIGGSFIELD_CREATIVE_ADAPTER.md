# Higgsfield creative-provider adapter

Offline, dry-run-first MarketOS port. It does not generate media, install
the Higgsfield CLI/SDK, register an MCP server, or authorize publication.

## Sources inspected

| Repository | Commit / tag | License | Adopted | Rejected |
| --- | --- | --- | --- | --- |
| higgsfield-ai/skills | `d071406` / VERSION 0.12.0 | MIT | Workflow names: product photoshoot, marketplace cards, brand kit, explainer, generate | Hidden prompt templates, skill install, CLI auth |
| higgsfield-ai/cli | `dc7e2d2` | MIT | Job/status/cost grouping as a dry-run lifecycle | Mutation commands, auth login, website deploy |
| higgsfield-ai/higgsfield-client | `aefd1ca` / 0.1.0 | Apache-2.0 | Polling/error/timeout taxonomy; optional import detection | Live subscribe/submit, env credentials |
| higgsfield-ai/higgsfield-js | `e3f2742` / npm 0.2.6 | MIT (`package.json`) | Server-only client boundary | Browser SDK, axios credential calls |
| higgsfield-ai/cursor-plugin | public main / plugin 1.1.0 | MIT | Agent-tool grouping reference | Marketplace plugin registration, MCP client |
| higgsfield-ai/fnf-local-pluging-bridge-mcp | public main | MIT | None | After Effects, Blender, mailbox, OS scripting |
| higgsfield-ai/higgsfield | `v0.0.4-rc` | Apache-2.0 | None | GPU orchestration / multi-node training |

Attribution: Higgsfield AI copyright notices remain on the upstream
repositories. This adapter reimplements compatible concepts only.

## Why GPU orchestration and desktop MCP were rejected

MarketOS is not a distributed training platform. The `higgsfield` GPU
framework allocates nodes and trains LLMs. The FNF local MCP bridge drives
After Effects and Blender on the operator desktop. Both are out of scope
and would create a second mutation surface.

## Modes

`fixture`, `manual_import`, `dry_run`, `blocked_live`, `live_unavailable`.
Draft modes never become observed, published, launch-authorized, or
commercially proven.

## Live prerequisites (recorded, not executed)

human approval, evidence refs, budget/credit cap, idempotency key, audit
event, rollback plan, provider terms review, privacy review.

## Rollback

Delete `evaluation/creative/` and `tests/creative/` and
`docs/ai/HIGGSFIELD_CREATIVE_ADAPTER.md`.
