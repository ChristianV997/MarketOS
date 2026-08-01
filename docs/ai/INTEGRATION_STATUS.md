# Integration Status

Updated: 2026-07-31

This is a compact status ledger. Confirm current code before relying on it.

| Area | Status | Rule |
|---|---|---|
| Signal cache | Implemented and instrumented | Preserve source provenance and freshness metrics |
| Health/readiness | Implemented | `/ready` must reflect runtime initialization |
| Commerce loop | Implemented/dry-run capable | Keep one canonical entry point per execution mode |
| External ads/payments | Guarded | Require configured credentials and approval/risk gates |
| Grafana | Dashboard assets/integration dependent | Keep Prometheus metric names stable |
| OSS sidecars | Evaluation/adapter stage | No unreviewed source copying or live writes |
| Ollama | Ready and locally validated | `http://localhost:11434`, model `qwen2.5:0.5b`; opt-in for low-risk tasks only; verify with `verify_local_integrations.py` |
| Obsidian handoff | Ready via local filesystem bridge | Writes only generated handoffs to `AI Engineering/Session Handoffs/`; REST/MCP remains disabled; verify with the same command |
| Serena | Configured for MarketOS and registered with Codex/Claude Code | Official `oraios/serena` via `uvx`, Python language server, `.serena/project.yml`; use symbol navigation by default |
| Repomix | Installed and smoke-tested | Global `repomix` `1.17.0`; use only for bounded snapshots such as `backend/inference`, never the whole repository by default |

Avoid adding a second client or loop without documenting migration and ownership.
