# Workflow Orchestrator

MarketOS workflows are synchronous, checkpointed, and fail-closed. The default `full_market_cycle` composes safe local import, discovery, refinement, acquisition planning, pipeline refresh, calibration, validation, deliverable, executive-intelligence, and summary stages.

Each stage records status, outputs, warnings, errors, checkpoints, and timeline events in `state/workflow_registry.json`. Runs can be inspected, stopped after a stage, resumed from safe checkpoints, or replayed only through explicitly safe paths. Full market cycles also include simulated portfolio optimization before the final summary.

All workflow payloads are recursively checked for live, spend, publish, send, order, payment, launch, mutation, and external URL flags. No background daemon or live connector is enabled. Obsidian run, timeline, and runbook notes are optional.

The optional `creative_intelligence` stage creates local creative drafts after commercial intelligence. It never schedules, publishes, or evaluates live advertising.

API examples: `POST /api/workflows/run`, `POST /api/workflows/{id}/resume`, `POST /api/workflows/{id}/replay-stage`, and the inspection endpoints under `/api/workflows`.

The full safe workflow may now produce an operating plan after portfolio optimization. The `operating_cycle` runbook covers optimization, operating-plan creation, executive review, and summary. It produces local planning artifacts only; it does not execute tasks or write external calendars.

The separate `cockpit_preview_cycle` can resolve an operating plan into allowlisted cockpit actions without execution. Actual cockpit execution is explicit, approval-gated, synchronous, and outside the default full market cycle.

The full market cycle includes a deterministic `commercial_intelligence` stage after pipeline refresh and before validation planning.
