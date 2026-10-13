# Parallel Work Matrix

Updated: 2026-10-12

This document defines durable coordination rules; it is not a live work board. Do not put current PR numbers, changing owner assignments, WIP queues, or status snapshots here. Refresh live status before acting and keep task-specific ownership and evidence in the existing task, PR, or handoff record. Do not create a second tracker or new coordination automation for this policy.

## Ownership and write boundaries

- **One writer per path.** Assign exact files or non-overlapping directory scopes to one writer. Reviewers and coordinators are read-only for another writer's assigned paths unless the owner explicitly releases them. Resolve overlapping scopes before work starts.
- **Make ownership auditable.** The existing task/PR/handoff record must name the exact canonical `AGENT_ID` and `LANE_ID`, branch, worktree path, lifecycle status, base SHA, current head SHA, exact assigned/reserved paths, acceptance criteria, and merge gate. At assignment time, record the starting head even when it equals the base and mark changed paths `none`; update the head and changed-path inventory at handoff. Include staged, unstaged, and untracked paths in that inventory. A branch name, commit author, clean status, or filename alone does not establish ownership.
- **Isolate the writer.** After checking ownership, use a dedicated worktree at the refreshed base when the canonical checkout is shared, dirty, or stale. Only the named writer edits assigned paths. Keep reviewers read-only and use one designated integration authority for cross-branch integration, rebases, merges, and closes.
- **Require explicit release.** Another agent must not take a dirty or reserved path until its named owner explicitly releases that exact path in the existing coordination record. The release identifies the owner, branch/worktree, last head SHA, released paths, and the state/disposition of staged, unstaged, and untracked content. Inactivity, a clean-looking checkout, a commit, or a stale status snapshot is not release. If the owner cannot be reached, hold the path and escalate; do not infer abandonment.
- **Deduplicate agent aliases before dispatch.** Resolve display names and channel-specific aliases to one canonical `AGENT_ID` in the existing task/handoff record, then send at most one prompt per identity for the same work item. For example, “Antigravity A” and “Antigravity Agent A” are one agent, not two assignments. If identity is ambiguous, pause dispatch and resolve it rather than sending duplicate prompts.

## Lifecycle and disposition

Record one current lifecycle status in the existing task/PR/handoff record and refresh it before acting:

- **Active:** the named owner and reserved write-set remain authoritative; do not reassign without explicit release.
- **Blocked:** preserve the owner and write-set, record the blocker and next unblock action, and do not silently reassign dirty or reserved paths.
- **Merged:** record the integrated commit/PR and release the exact paths only after verifying the merge and the resulting base; a merged status is not permission to edit another branch before refresh.
- **Superseded or abandoned:** record the superseding task/PR or explicit disposition, last head SHA, and exact path release evidence. Until that evidence exists, treat the prior reservation as active and escalate ambiguity.

## Refresh before acting

Before assigning, resuming, taking over, or declaring work ready, refresh the relevant state rather than trusting this durable matrix or an old chat message:

1. Read `AGENTS.md`, `docs/ai/CANONICAL_ARCHITECTURE.md`, and `docs/ai/CANONICAL_PATHS.md`; run the required session-start and capability checks.
2. Refresh permitted remote refs in an isolated checkout and record exact base/head SHAs. Inspect current open-PR base/head SHAs, changed paths, and handoff/ownership notes; do not infer path ownership from PR titles or authors.
3. Inspect relevant `git worktree list --porcelain` entries, including both uncommitted/untracked status and committed path deltas against the refreshed base. Detached validation/evidence snapshots are not active owners unless explicitly assigned; preserve their contents and status.
4. Compare the findings with the existing ownership record. If any path is dirty, reserved, changed on another branch/PR, or ownership evidence is incomplete, stop and resolve ownership before editing. If live refresh is unavailable, label cached evidence as such and leave current remote ownership unverified.

Never switch, pull, reset, clean, stash, or discard content in the canonical checkout to make it appear current. Preserve all dirty and untracked canonical-checkout content. Refresh refs and do work in an isolated checkout; do not overwrite an active dirty owner.

## Handoff and evidence

A handoff reports the exact base and current head SHAs, branch/worktree, assigned and changed paths, ownership/release evidence, rollback, and one next action. Classify every relevant check separately:

| Evidence class | Required handoff statement |
|---|---|
| **Executed** | Exact command and scope, target SHA, exit/result, and test or step counts. Report failures as well as passes. |
| **Pending** | Not run yet, why it remains pending, and who/what must run it next. It is not a pass. |
| **Zero-step** | The check plan ran but executed zero steps (or selected zero tests); state why and whether that is expected. It is not evidence that a check passed. |
| **Skipped** | Deliberately omitted or not applicable; give the reason and any approval or policy basis. Do not collapse this into pending or pass. |
| **Local-only** | Identify the local checkout/worktree and exact head SHA. Local evidence does not establish hosted CI, remote PR state, or another worktree's state. |

Do not claim “all checks passed” when checks are pending, zero-step, skipped, unavailable, or supported only by local evidence. A test recommendation, planned command, or test file present in the repository is not an executed check.

## Canonical-checkout and scanner safety

- Keep unrelated dirty or untracked content intact. Stage only explicitly assigned paths; never include artifacts, credentials, `.env` files, caches, raw provider payloads, scanner findings, browser traces, or unrelated work.
- Follow `AGENTS.md` scanner restrictions: security-scanner work remains fixture/output-metadata or plan-only by default; do not install or execute scanners, call GitHub or other external services, read credentials, or retain raw findings/secrets/client data. Any explicitly permitted local scanner execution must use its stated allowlist, `shell=False`, bounded time/output, redaction, no credentials/network/uploads, and fail closed when unavailable.
- Only the designated integration authority may rebase another agent's work, merge, or close another agent's PR. Do not open duplicate PRs for the same outcome; review scope, checks, risk, and exact changed paths before integration.

## Review basis

For parallel assignments, apply the single-owner, explicit-scope, branch/worktree-isolation, evidence, and merge-gate principles in [ECC team-agent orchestration](https://github.com/affaan-m/ECC/blob/main/skills/team-agent-orchestration/SKILL.md). Before a non-trivial assignment, review scope, boundaries, failure cases, and test coverage in the spirit of [gstack plan-eng-review](https://github.com/garrytan/gstack/blob/main/plan-eng-review/SKILL.md.tmpl). These are guidance references, not a requirement to install their tools or create a new tracker.
