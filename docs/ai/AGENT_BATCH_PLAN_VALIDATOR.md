# Agent Batch Plan Validator

Pre-dispatch check for an agent batch plan (`MarketOS.AgentBatchPlan.v1`). Run it
before any agent starts. It rejects duplicate assignments, overlapping write
scopes, unsafe paths, broken dependency graphs, and wrong batch counts or sizes.

It is read-only. It never dispatches agents, reads credentials, calls GitHub,
GitLab, a provider, or a host, and never changes git state. The post-run
counterpart is `agent_output_eval.audit_handoff_batch`, which audits handoff
prose after work finishes. This validator does not replace it.

## Usage

```bash
python scripts/ai/validate_agent_batch_plan.py docs/ai/agent_batch_plan.sample.json
```

- Exit `0`: the plan is valid.
- Exit `2`: the plan is invalid, unreadable, or the policy failed to load.
- Output is a sorted JSON report on stdout. It never echoes the input path or raw
  values. Invalid values are reported by location and code only.

Options: `--policy PATH` replaces the default roster policy.

## Files

| File | Role |
|---|---|
| `scripts/ai/agent_batch_plan.py` | Validator library: parsing, checks, report |
| `scripts/ai/validate_agent_batch_plan.py` | CLI wrapper |
| `scripts/ai/agent_batch_policy.json` | Roster, batch order, sizes, forbidden path segments (data, not code) |
| `docs/ai/agent_batch_plan.sample.json` | Sample plan for the current roster (placeholder scopes, IDs only) |
| `tests/ai/test_agent_batch_plan.py` | Tests |

## Policy: the four-batch roster

The agreed roster lives in `scripts/ai/agent_batch_policy.json`, not in code.

| Batch | Size | Agents |
|---|---|---|
| 1 | 5 | hermes-bots-team, hermes-agents-a, hermes-agents-b, grok-bots-team, antigravity-a |
| 2 | 5 | antigravity-b, antigravity-c, antigravity-d, cursor-a, cursor-b |
| 3 | 6 | cursor-c, cursor-d, claude-a, claude-b, claude-c, claude-d |
| 4 | 6 | codex-a, codex-b, codex-c, codex-d, grok-chat-a, grok-chat-b |

To change the roster, edit the policy file. `load_policy` rejects a policy whose
`size` does not match its agent list, a batch number out of order, or an agent
listed twice. Update the roster assertion in `test_policy_encodes_the_agreed_four_batch_roster_as_data`
at the same time, since that test pins the agreed roster.

## What the plan must contain

- Top level: `schema`, `session_id`, `batches`. Nothing else is allowed.
- Each batch: `batch` (its policy number) and `assignments`.
- Each assignment: `agent_id`, `task_id`, `prompt_id`, `primary_paths`,
  `fallback_paths` (may be empty), optional `depends_on`.
- Prompt text is not allowed. The plan refers to prompts by `prompt_id` only.

## Checks

| Area | Codes |
|---|---|
| Shape and size | `manifest_unreadable`, `manifest_too_large`, `manifest_malformed`, `manifest_duplicate_key`, `manifest_not_object`, `manifest_too_deep`, `unknown_field`, `missing_field`, `invalid_type`, `too_many_items`, `schema_mismatch` |
| Policy (load time) | `policy_unreadable`, `policy_too_large`, `policy_malformed`, `policy_duplicate_key`, `policy_invalid`, `policy_batch_order`, `policy_size_mismatch` |
| Batches | `batch_count_mismatch`, `batch_order_mismatch`, `batch_size_mismatch`, `agent_wrong_batch` |
| Agents | `duplicate_agent_assignment`, `missing_agent`, `unknown_agent`, `invalid_identifier` |
| Identifiers | `duplicate_task_id`, `duplicate_prompt_id` |
| Paths | `path_absolute`, `path_traversal`, `path_not_normalized`, `forbidden_path`, `invalid_path`, `empty_scope`, `duplicate_path` |
| Overlap between agents | `primary_primary_overlap`, `primary_fallback_overlap`, `fallback_fallback_overlap` |
| Dependencies | `unknown_dependency`, `dependency_self`, `duplicate_dependency`, `dependency_not_earlier_batch`, `dependency_cycle` |
| Sensitive content | `sensitive_value`, `sensitive_field` |

### Path rules

- Repo-relative only. Forward slashes, no leading `/`, no drive letter, no UNC path.
- Canonical form: no `\`, no `./`, no `//`, no trailing `/`, no surrounding spaces.
- No `..` segment, no `:`, no control characters. At most 240 characters.
- Forbidden segments: `.git`, `artifacts`, `credentials`, `node_modules`,
  `secrets`, and any segment starting with `.env`. These come from the policy.

### Overlap rules

- Two paths overlap when they are equal, or one is inside the other's directory.
  `shared` overlaps `shared/x.md`. `shared` does not overlap `shared2`.
- Overlap is checked between **different** agents only. One agent's primary and
  fallback may share a path.
- Overlap is rejected even when dependencies would order the two agents. The
  validator does not reason about sequencing. If two agents must touch the same
  path, make it one assignment.

### Dependency rules

- Every `depends_on` entry must name a task in the same plan.
- A task may depend only on a task in an earlier batch while
  `require_earlier_batch_dependencies` is `true` (the current policy). Setting it
  to `false` allows same-batch dependencies, and cycles are then detected and
  reported by `dependency_cycle`. The `ids` list names the cycle members only, not
  tasks that merely wait on a cycle.

## Limits

| Limit | Value |
|---|---|
| Manifest size | 64 KiB |
| Policy size | 16 KiB |
| Nesting depth | 8 |
| Items per path or dependency list | 16 |
| Path length | 240 characters |
| Identifier length | 64 characters (`[a-z0-9][a-z0-9._-]*`) |

A batch with more assignments than its policy size still fails `batch_size_mismatch`,
but only the policy's slots are checked in detail. The sensitive-content sweep covers
the whole input. This keeps the overlap check bounded by the roster size.

## Not checked

- Whether a path exists in the repository.
- Open PRs, branch ownership, or active worktrees. Check these with
  `docs/ai/PARALLEL_WORK_MATRIX.md` and `gh pr list` before writing a plan.
- Glob patterns. Scopes are literal paths only.
- The safety of the prompt behind a `prompt_id`. Prompt text never enters the plan.
- Whether an agent's work actually stayed inside its scope. That is the post-run audit's job.

## Rollback

Delete the five files listed under Files and this document. Nothing else in the
repository imports this validator.
