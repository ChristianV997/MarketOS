# MarketOS AI Tooling Setup and Supply-Chain Manifest

## Purpose

This document is the human-readable companion to
[`AI_TOOLING_MANIFEST.json`](AI_TOOLING_MANIFEST.json). It records the local
tooling surfaces that can be observed without configuring another agent's
private account, and it separates installed presence from trustworthy source
verification. It is a MarketOS documentation artifact, not an installer and
not a new orchestration authority.

The review was performed against MarketOS `origin/main` at
`94a38ca2d9d6071611b4e12222770580458e688d`. The canonical checkout contained
pre-existing unrelated dirty paths; they were not edited. CoderOS was audited
read-only at `b980e90b49ea7c0639094f3060ced5aaf772a571` and remains a separate,
frozen control-plane repository. No CoderOS files were changed.

## Evidence and disposition

The manifest uses two independent fields:

- `installation_state` describes what the host inventory observed. A command
  found on `PATH` is only `installed_local_presence`; it is not proof of login,
  credentials, a working provider, or a successful model call.
- `disposition` is the MarketOS decision: `install`, `reference_only`, `defer`,
  or `reject`. This task performed no install. Existing local caches are
  documented as `reference_only` unless a stronger reason exists to block
  their use entirely.

Where present, `configuration_state` is intentionally conservative:
`not_configured_verified` means the command/package was observed but no
private profile, login, token, or account configuration was inspected. A
configured state is never inferred from installation alone.

Evidence classes are deliberately explicit: `actual_executed`,
`installed_local_presence`, `read_only_probe`, `source_metadata`,
`unavailable`, `timed_out`, `collection_failed`, and `not_run`. A zero command
result, missing log, or detected binary cannot be upgraded to execution
evidence.

## Observed local surfaces

| Surface | Local evidence | Source/license posture | Decision |
| --- | --- | --- | --- |
| Codex | Native executable and bundled `codex-app-tools` `0.1.4` cache | OpenAI plugin metadata says proprietary; no Git pin | `reference_only` |
| Claude Code | Native executable | Official setup docs available; binary revision not pinned | `defer` |
| Hermes | Native executable | Official Hermes repository identifies MIT; local revision not pinned | `defer` |
| Gemini CLI | Native executable | Official repository/docs identify the extension surface; local revision not pinned | `defer` |
| Antigravity | Command unavailable | No trusted local implementation identified | `defer` |
| Jules | Native executable | Google service/CLI docs; account and package revision not inspected | `defer` |
| Grok | Native executable | Official `xai-org/grok-build` source identified, local revision/license not pinned | `defer` |
| OmniRoute | Native npm command, version `3.8.49` | Local package metadata identifies MIT and `diegosouzapw/OmniRoute`; no Git pin | `reject` |
| Ollama | Native executable, version `0.34.2` | Local/free runtime; bounded dev-stack check found a model inventory, but model names and binary revision are not recorded | `reference_only` |
| CoderOS | Local repository plus read-only probe | MIT at local HEAD; separate repository and no MarketOS import | `reference_only` |
| ECC | Cache `2.2.1` plus command | MIT in local cache; no Git revision pin in cache | `reference_only` |
| gstack | Adaptation cache `0.1.0`, native command unavailable | MIT; upstream commit `85fd9db554ae4aaaa6d356d2daf873121ee85bdd` recorded in local notice | `reference_only` |
| MCP Registry | No local connector | Discovery registry only; each server needs its own review | `reference_only` |
| Render MCP | Not installed | Official server can deploy and change infrastructure | `reject` |
| OpenRouter skills | Not installed | Would add hosted routing and credentials | `reject` |
| GitHub CLI | Native executable | Official MIT CLI; remains the sole GitHub command authority | `reference_only` |

The complete machine-readable records, paths, permissions, compatibility, and
rollback instructions are in the JSON manifest. The local `.codex` and
`.agents` skill roots were inventoried without modifying them. System-managed
skills and cached third-party content are not MarketOS source code and are not
copied into the repository.

## Official source references

These links are documentation or source references, not installation commands:

- [OpenAI plugins](https://developers.openai.com/plugins) and [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Anthropic Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/getting-started) and [CLI/MCP reference](https://docs.anthropic.com/en/docs/claude-code/cli-usage)
- [Gemini CLI extension reference](https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md)
- [Official MCP Registry documentation](https://registry.modelcontextprotocol.io/docs)
- [Render MCP server documentation](https://render.com/docs/mcp-server)
- [OpenRouter skills guidance](https://openrouter.ai/agents)
- [Hermes Agent source](https://github.com/hermes-agent-org/hermes)
- [Grok Build source](https://github.com/xai-org/grok-build)
- [Jules CLI reference](https://jules.google/docs/cli/reference)
- [CoderOS source](https://github.com/ChristianV997/CoderOS)
- [ECC source](https://github.com/affaan-m/ECC)
- [gstack source](https://github.com/garrytan/gstack)

Source links do not substitute for pinning. Before any future adoption, record
the exact commit or immutable release, verify the license at that revision,
review transitive dependencies, and run the bounded security review. Hosted
MCP services and agent platforms need an additional permission and data-flow
review even when their source repository is open.

OmniRoute is explicitly rejected here because its local package describes a
multi-provider router with automatic fallback. MarketOS must not gain a second
routing authority beside its existing routing policy. Ollama is different: it
is a local/free inference runtime and remains reference-only unless an operator
selects it for a bounded offline task. The bounded dev-stack check confirmed
that a model is available, but no model name was recorded and no model
invocation was performed in this audit.

The installed Claude, Hermes, Gemini, Jules, and Grok commands are executable
presence only. No private configuration, profile, token, login, or account
state was inspected. In particular, a Hermes binary does not prove that a
Hermes profile exists, and a Jules GitHub/cloud authorization is not the same
credential or permission as Render OAuth/API-key authorization.

GitHub remains represented by the official `gh` CLI only. No second GitHub
connector, MCP server, or custom PR authority is introduced by this manifest.

## Permission and model-cost policy

MarketOS remains offline by default. Repository inspection, fixture-backed
tests, and deterministic local reasoning are allowed when they do not read
credentials or call providers. Network connectors, MCP servers, OAuth/API
keys, hosted models, deployment systems, and any external mutation require
explicit approval outside this manifest task.

Command availability does not establish whether a model is free, paid,
authenticated, or reachable. Ollama may be used as a local runtime only when
explicitly selected; Codex, Claude, Gemini, Jules, Grok, and OpenRouter are
host/account/provider dependent. No model or provider call was made for this
inventory.

## Supply-chain controls

1. Prefer official documentation and source repositories.
2. Treat a cache version as a package version, not a source revision.
3. Keep an unavailable revision as unavailable rather than substituting a
   branch, tag, or synthetic SHA.
4. Review plugin skills, MCP manifests, hooks, shell commands, and transitive
   dependencies before enabling them.
5. Keep credentials outside the repository and never place them in this
   manifest.
6. Do not allow a plugin, external agent, or model router to become a second
   MarketOS event, economics, evidence, export, or execution authority.
7. Keep CoderOS read-only and separate. It can provide operator evidence, but
   it is not imported into MarketOS and cannot authorize live actions.

The historical source-adaptation catalog contains some source entries whose
revisions are not independently verified in the local checkout. Those entries
are intentionally not reused as pins here. This prevents a plausible-looking
source record from becoming supply-chain evidence merely because it is already
stored in a local catalog.

## Rollback

This change is documentation-only. Roll back the single documentation commit,
or remove the two files, to restore the previous repository state. No host
configuration, plugin selection, credential, CoderOS file, provider, network
connector, or deployment setting was changed. If a future operator enables a
listed tool, rollback must use that tool's own scoped uninstall/revoke process;
do not delete shared caches or unrelated user configuration.

## Validation

From the isolated MarketOS worktree:

```powershell
git diff --check
python -m json.tool docs/ai/AI_TOOLING_MANIFEST.json
python scripts/ai/session_finish.py --dry-run
python scripts/ai/pr_readiness_report.py --json
```

`compileall` is not required because this contribution contains no Python
files. GitHub Actions evidence remains separate: runnerless, zero-step, or
missing-log jobs are `ci_unavailable`, never a pass.
