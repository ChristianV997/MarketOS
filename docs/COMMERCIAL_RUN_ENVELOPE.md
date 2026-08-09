# CommercialRunEnvelope

The durable, auditable record every service-module call produces.
Defined in `backend/experiments/envelope.py`.

## Why it exists

Every service module (`services.product_research`, `services.unit_economics`,
etc.) needs a consistent answer to: *what ran, for which workspace, with
what inputs, producing what outputs, and what's the paper trail?*
`CommercialRunEnvelope` is that answer — built once in `backend/experiments/`
and reused by all 7 modules, rather than each module inventing its own
run-tracking shape.

## Design decision: it subclasses `BaseArtifact`

Rather than build a second artifact/lineage system, `CommercialRunEnvelope`
subclasses the pre-existing `backend.contracts.base.BaseArtifact` (already
used by `CommerceSignal`, `LaunchPlan`, `CampaignOutcome`, etc.). This gets
it, for free:

- `artifact_id` (content-addressed, deterministic per construction)
- `workspace` (BaseArtifact's lineage-namespace field — set equal to
  `workspace_id` at construction so it carries real tenant meaning here,
  without changing what that field means for other artifact types)
- `parent_ids` (lineage chain, if a future module wants to link envelopes)
- `replay_hash` (content hash for replay-dedup)
- `.to_dict()` / `.from_dict()` (JSON-safe serialization)
- Registration into the existing `backend.contracts.registry.ArtifactRegistry`
  via `backend.experiments.registry.ExperimentRegistry` — a thin,
  `artifact_type`-filtered *view*, not a second store.

## Fields

| Field | Meaning |
|---|---|
| `experiment_id` | Same value as `artifact_id`, exposed under a clearer domain name |
| `service_name` | Which module produced this (`"product_research"`, `"unit_economics"`, ...) |
| `workspace_id` | The real tenant this run belongs to |
| `mode` | `"dry_run"` or the workspace's live mode |
| `status` | `created \| running \| completed \| blocked \| failed` |
| `inputs` | Everything the caller passed in (product name, prices, assumptions, ...) |
| `outputs` | The module's final result, once completed |
| `proposed_spend` / `actual_spend` | For modules where real spend is relevant (currently `ecommerce_operator`) |
| `audit_log_refs` | `event_store` workflow IDs — see "Audit trail" below |
| `blocked_reasons` | Populated when a launch guard or checklist blocks the run |
| `started_at` / `finished_at` | Timestamps |

## Lifecycle

```
created → running → completed
                  ↘ blocked   (a guard/checklist failed — see docs/LIVE_MODE_SAFETY.md)
                  ↘ failed    (an unexpected exception reached the envelope layer)
```

Every service module follows the same sequence:
1. Construct the envelope, `registry.register(envelope)`.
2. `log_transition(envelope, "experiment_created")`.
3. `envelope.mark_running()`, `log_transition(envelope, "experiment_running")`.
4. Do the actual work (already fail-soft in every module — see each
   module's own docstrings for its specific try/except boundaries).
5. `envelope.mark_completed(outputs)` (or `mark_blocked(reasons)` /
   `mark_failed(reason)`), `log_transition(envelope, "experiment_completed")`.

## Audit trail: two logs, on purpose

`ExperimentRegistry.register()` writes through `backend.contracts.registry.
ArtifactRegistry`, which durably logs to `backend/events/log.py` (→
`backend/runtime/replay_store.py`) — this is what lets envelopes survive a
process restart (`ExperimentRegistry.__init__` calls
`hydrate_from_replay()` on construction).

Separately, `backend.experiments.audit_log.log_transition()` appends each
status change to `backend.orchestration.event_store` (→
`state/workflow_executions.jsonl`) — the same durable log every dry-run/
shadow-mode gate elsewhere in this repo already writes to
(`organic_gate.py`, `tiktok_ads.py`, `inventory_sync.py`,
`live_mode_checklist.py`). `envelope.audit_log_refs` holds the workflow IDs
this produces; `backend.experiments.audit_log.transitions_for(envelope)`
reads them back.

These are genuinely two different logs serving two different existing
purposes in this codebase (artifact/lineage replay vs. workflow/shadow-mode
audit) — unifying them was flagged in the original design pass as a
pre-existing fork in the codebase, out of scope for this effort to fix.

## Persistence: `ArtifactStore`

Alongside the two logs above, every module also saves its structured
result and rendered report under:

```
state/workspaces/{workspace_id}/experiments/{experiment_id}/result.json
state/workspaces/{workspace_id}/experiments/{experiment_id}/report.md
```

via `backend.workspaces.artifact_store.ArtifactStore` (built on the same
`state_path()`/`save_json_atomic()` idiom every other MarketOS store uses)
and `services.reporting.save_report_artifacts()`. This is the actual
client-deliverable file — see `services.reporting.export_client_report()`
to resolve its path.

## Example

```python
from backend.workspaces.client_workspace import ClientWorkspace
from services.unit_economics import run_unit_economics
from backend.experiments.audit_log import transitions_for

ws = ClientWorkspace(name="own-store")
result, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws)

print(envelope.experiment_id, envelope.status)   # e.g. "a1b2c3...", "completed"
print(transitions_for(envelope))                  # every logged status change
```
