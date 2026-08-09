# Operating Cadence and Execution Calendar

MarketOS converts the simulated portfolio optimization plan into a local operator plan. It creates tasks, task packets, day buckets, review prompts, progress snapshots, and optional Markdown/ICS calendar artifacts.

## Safety model

This layer is planning-only. It does not execute task endpoints, create background jobs, write to Google Calendar, contact customers, place orders, spend money, publish, or mutate commerce systems. Endpoint and payload fields in task packets are references for an operator to review.

For explicit approval-gated execution of selected internal tasks, see [SAFE_LOCAL_EXECUTION_COCKPIT.md](SAFE_LOCAL_EXECUTION_COCKPIT.md). The cockpit does not execute external or business actions.

## Weekly cycle

1. Generate or select a portfolio optimization plan.
2. `POST /api/operations/plans` to create a weekly operating plan.
3. Review blocked tasks, dependencies, evidence provenance, and checklists.
4. Use task packets to perform approved local/manual work and record registry IDs.
5. Review the local calendar or ICS text; importing ICS into an external calendar remains a manual operator decision.
6. Update task status using `/api/operations/tasks/{task_id}/status`.
7. Create a progress review and carry unresolved work into the next plan.

## Tasks and packets

Actions map to safe planning task types such as evidence acquisition, refinement, pipeline refresh, validation sprint, deliverable generation, source calibration, and executive review. Dependencies are assigned deterministically. Every task includes acceptance criteria, a checklist, expected outputs, and safety notes. Each packet adds a done definition and troubleshooting guidance.

## Calendar and review cadence

Calendar blocks use `day_1` through `day_5` and deterministic slots. Blocked work is placed in `backlog`; it is not treated as scheduled execution. ICS output is plain local text with an explicit local-only marker. Review cadence includes daily start/end prompts, weekly review, blocker review, and deliverable review when relevant.

## Progress snapshots

Progress snapshots are operator-provided records. They summarize completed, blocked, cancelled, and carried-over task IDs, produced outputs, blockers, and next-cycle recommendations. No reminders or daemon are created.

## Current limitations

- Local planning and state registries only.
- Synchronous API calls; no background execution.
- No external calendar writes.
- No automatic task execution.
- No live connector or production mutation.
