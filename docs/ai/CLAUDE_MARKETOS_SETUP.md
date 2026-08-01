# Claude Code Handoff: MarketOS AI Development Stack

Updated: 2026-07-31

## Repository

- Path: `C:\Users\HP\Documents\MarketOS`
- Repository: MarketOS
- Use this repository only; do not mix it with NeuroTopology-Sim or AI-DevStack.
- Read first: `docs/ai/README.md`, `docs/ai/CANONICAL_ARCHITECTURE.md`, `docs/ai/KNOWN_GAPS.md`, and `docs/ai/INTEGRATION_STATUS.md`.

## Verified tools

| Tool | Status | Use |
|---|---|---|
| Serena | Ready | Default semantic navigation, symbol lookup, references, and bounded edits |
| Ollama | Ready | Optional low-risk local worker inference |
| Obsidian | Ready | One-way session-handoff capture through the local filesystem bridge |
| Repomix | Ready, v1.17.0 | Bounded snapshots only, mainly for external repositories or selected subsystems |
| Semgrep | Ready, v1.172.0 | Local and CI safety policy checks |
| uv | Ready | Official Serena runner and isolated Python tools |

## Serena

MarketOS is registered at `.serena/project.yml` with the Python language server. Serena is registered with Claude Code using:

```powershell
uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context=claude-code --project-from-cwd
```

Health check:

```powershell
$env:PYTHONIOENCODING='utf-8'
uvx --from git+https://github.com/oraios/serena serena project health-check C:\Users\HP\Documents\MarketOS
```

Use Serena first for symbol-level discovery and edits. Do not read the entire repository for ordinary tasks.

## Ollama

- API: `http://localhost:11434`
- Model: `qwen2.5:0.5b`
- Repository environment defaults are documented in `.env.example`.
- Provider: `backend/inference/providers/ollama.py`
- Use only for bounded, low-risk tasks such as summaries, classification drafts, and fixture drafts.
- Do not use it as final authority for security, payments, auth, tenant isolation, scientific claims, live ads, deployments, or architecture.

Verify:

```powershell
python scripts/ai/verify_local_integrations.py
python scripts/ai/benchmark_ollama.py --model qwen2.5:0.5b --task summarize --json
```

The model is operational but benchmark quality is not sufficient for automatic code edits.

## Obsidian

- Vault: `C:\Users\HP\Documents\Obsidian Vault`
- Destination: `AI Engineering\Session Handoffs\`
- No REST/MCP plugin is enabled.
- Never copy source code, secrets, or full chat transcripts into the vault.

Capture a handoff:

```powershell
python scripts/ai/generate_session_handoff.py --output docs/ai/SESSION_HANDOFF.md
python scripts/ai/push_handoff_to_obsidian.py --input docs/ai/SESSION_HANDOFF.md --dry-run
python scripts/ai/push_handoff_to_obsidian.py --input docs/ai/SESSION_HANDOFF.md
```

The repository Markdown handoff remains the source of truth.

## Repomix

Use only bounded paths. Example:

```powershell
repomix backend/inference scripts/ai docs/ai --compress --no-files --stdout
```

Do not pack the entire MarketOS repository by default. Exclude `.env`, credentials, state, logs, databases, caches, `node_modules`, virtual environments, generated artifacts, and unrelated repositories.

## Semgrep

Run the compact local wrapper:

```powershell
python scripts/ai/run_semgrep_policy.py
python scripts/ai/run_semgrep_policy.py --severity ERROR --fail-on-error
```

Policy: `semgrep/ai-safety.yml`. Current warning findings are review prompts around external writes; ERROR findings are blocking.

## Claude workflow

1. Check `git status` and preserve unrelated user changes.
2. Read the canonical AI files and the affected subsystem only.
3. Use Serena for symbol/reference navigation.
4. Use Context7 or current official documentation only when changing an external API or version-sensitive library.
5. Implement the smallest coherent change; search for existing equivalents before adding modules.
6. Run targeted tests first.
7. Run Semgrep on security-sensitive or external-write changes.
8. Run the full suite only when the change warrants it.
9. Generate a compact session handoff and optionally mirror it to Obsidian.
10. Report files changed, tests, risks, and the exact next action.

## Do not duplicate

- Do not create another inference router, commerce loop, feature-flag system, client per provider, memory API, or handoff system.
- Do not replace MarketOS orchestration with a second agent runtime.
- Do not install arbitrary MCP servers, skills, or plugins globally.
- Do not enable live ad, payment, publishing, fulfillment, or deployment actions without existing approval and risk gates.

## Known limitations

- Graphify is not installed because the package identity was ambiguous.
- Context7 is not configured because no verified local client configuration is present.
- CodeQL is deferred to release/security-sensitive analysis.
- Ollama is local and optional; its small model requires frontier-model review for any generated artifact.
