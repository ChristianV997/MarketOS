# Validation Sprint Plan (plan-only)

`plan_validation_sprint` and `build_validation_sprint_plan` in
`backend/discovery/validation_sprint_runner.py` produce a deterministic,
explainable preflight for a dry-run validation sprint. They plan; they do not
execute. Execution remains the separate `run_validation_sprint` entry point,
which this work does not change.

Status: implemented; unit- and integration-tested with synthetic data and
fixture-backed learning events. Not live-validated. No provider, network,
approval, spend, publishing, order, or messaging authority is granted.

**The plan is advisory.** `run_validation_sprint` does not read a plan, so its
governor, learning, and eligibility verdicts do not block execution. A caller
that runs a target the plan marked `blocked` bypasses those verdicts. Enforcing
them requires a change to the execution path and its own review.

## Calling it

- `plan_validation_sprint(candidates, *, requested_ids=None, evidence_records=(), learning_context=None, acknowledged_learning_for=(), budgets=None, portfolio=None, runaway=None, warnings=(), ...)`
  is pure. It reads no registry, writes no state, invokes no service, and
  transitions no stage.
- `build_validation_sprint_plan(workspace_id, opportunity_ids, limit, ...)` is
  the programmatic seam over the live registries. It only reads them. It fetches
  explicit ids only from the requested workspace, so another workspace's record
  is reported as not found. An explicit `opportunity_ids` list is an exact
  selection, and an empty list is blocked (`no_validation_targets`). Only `None`
  selects the validation-ready pool. The seam adds
  `opportunity_pool_may_be_truncated` or `evidence_pool_may_be_truncated` when a
  read reaches the registry's 1000-record page cap.
- The runner imports the governance packages only inside the planning functions,
  so importing the runner does not load them. A test enforces this.

`learning_context` accepts only `events`. Each event must name its
`learning_event_id`, `event_type`, `outcome`, `workspace_id`, `candidate_id`, and
`action_taken`. `event_type` and `outcome` come from the ledger's vocabularies,
and `action_taken` must be a governor action. Failure and success reasons must
come from the ledger's reason codes. Event keys must come from the ledger's
recognized set. Any other shape raises `ValueError`, so a misspelled key or value
cannot drop a constraint silently. Events are scoped to the planning workspace,
as the ledger scopes them: another workspace's event never constrains a
candidate here.

## Gates, in order

1. **Eligibility** (fail closed).
   - A repeated id is one target only when the very same record appears more
     than once. Separate records for one id, even identical copies, make the
     target ineligible (`duplicate_opportunity_records`).
   - The record must belong to the workspace (`workspace_mismatch`), be in stage
     `validation_ready`, and cite evidence (`no_evidence_recorded`).
   - Every cited evidence id must resolve in the supplied pool. An unresolved id
     is `unresolved_evidence_reference`. When the pool may be truncated, it is
     `evidence_reference_outside_loaded_pool` and the step is to reload the
     complete pool. An unresolved id is never guessed. Two different records
     sharing one evidence id make every candidate citing it ineligible
     (`duplicate_evidence_records`), whatever the input order.
   - At least one permitted service must have complete inputs.
   An ineligible target is listed with its reasons and never reaches the governor.
2. **Service plan**: the existing `build_validation_service_plan` contract. A
   service whose inputs are missing is skipped and its missing inputs are named.
   A service the contract cannot build is reported as a contract gap
   (`unsupported_service`), not as missing evidence. A candidate whose services
   are all unsupported is ineligible with exactly that reason.
3. **Governor** (`evaluation/companyos/resource_execution_governor.py`): one
   `deep_validate_product` decision per eligible target. The shared quota (5 per
   cycle), the `report_generation_quota` budget (aggregated across targets), the
   opportunity-score floor (0.60 on a 0–1 scale; the 0–100 opportunity score is
   divided by 100), and the runaway caps all apply. When the governor's own budget
   check marks a projection above its approval threshold, the target is
   `awaiting_approval` with approval type `budget_approval_threshold` for the
   `finance_manager` role. The governor records that threshold but does not
   enforce it, so the plan does.
4. **Learning** (`evaluation/companyos/learning_ledger.py`). Constraints are
   candidate-scoped: a constraint never reaches another candidate. A constrained
   candidate stays blocked until its own id appears in
   `acknowledged_learning_for`, which a human-reviewed caller sets.
   Acknowledgement never applies to other candidates, and the constraint stays
   visible on the released target.
   - A recurring TrustOS blocker (`trustos_recurrence_requires_trustos_review`)
     is never released by acknowledgement. It needs TrustOS review.
   - More than 25 matching events for one candidate and action exceed the
     ledger's review bound. The ledger keeps 25 events in `learning_event_id`
     order, not by recency, so a higher count can drop a kill. The target is
     blocked with `learning_history_exceeds_review_bound` rather than planned on
     a truncated history.
5. **Preview scorecard**: the existing `build_validation_scorecard` builds a
   preflight preview from the candidate's own evidence, with a deterministic
   `scorecard_preview_*` id, `metadata.registered = False`,
   `metadata.preflight_only = True`, and `metadata.governor_status` equal to the
   target's final status. Every preview service result has status `skipped`,
   since nothing executed. Governor blockers appear only as that result's
   `blocked_reasons`, and a service that was not run is marked
   `not_executed_in_plan`. The preview's `validation_score` therefore reflects
   preflight gaps only. It is never written to the scorecard registry, and it
   cannot recommend launch, because no service has completed.

Governance runs in canonical order (score descending, then name, then id),
regardless of input or request order, so the shared quota and budget fall on
the same targets. `limit` (at most 25) is applied to found candidates after that
ordering and is never silent: a found, explicitly requested opportunity past the
limit is listed as `ineligible` with reason `beyond_limit`, and the plan status
reflects it. An unknown requested id is always `opportunity_not_found`, never
`beyond_limit`. When candidates are selected rather than requested, the plan
carries `validation_ready_beyond_limit:<n>` in `warnings`.

Only targets the plan keeps consume the shared quota and budget. A held or
blocked target does not, so it cannot starve the others.

## Target and plan statuses

| Target status | Meaning |
| --- | --- |
| `ineligible` | Failed an eligibility gate; the reasons say which. The row carries no name or stage from another workspace. |
| `blocked` | Governor `soft_block` or `hard_block`; reasons are the governor's blockers. |
| `awaiting_approval` | Governor requires approval or finance review. The plan names the approver role. The approval is listed only for this status. Gap reasons (missing inputs, missing evidence, unsupported service) stay alongside the approval reason. |
| `partial` | Eligible and governor-permitted, but a service lacks inputs, the preview names missing evidence, or a service is a contract gap. |
| `planned` | Governor-permitted, with nothing missing. |

The plan status is `planned` only when every target is `planned`; `blocked`
when nothing is governed; otherwise `partial`.

## Output

`ValidationSprintPlan.to_dict()` contains a `plan_id`, every candidate with its
eligibility and reasons, the governor decision per target, learning
constraints, preview scorecards, `approvals_required`, `next_safe_steps`,
`governor_summary`, `execution_handoff`, `warnings`, and `safety`.

The `plan_id` digests the inputs (requested ids, limit, candidate fields that
affect decisions, evidence ids, the full learning events, policies,
acknowledgements, and warnings) and the full output. Changing a budget, an
opportunity's type or category, or a learning event's content changes the id.

The handoff is never authorized (`authorized: false`). Its payload is shaped for
`run_validation_sprint` and sets `apply_transitions: false`, and it deliberately
omits `objective`, so the run's own default objective is persisted. Setting
`apply_transitions: false` does not make the run side-effect-free. The handoff
lists what the run still does: service executor invocations, a validation sprint
registry write, an opportunity registry write, and an Obsidian sync attempt.

## Not evaluated by the plan

- TrustOS and client-workspace isolation gates. The governor defaults both to
  `allow`; `safety` reports them as `not_evaluated_by_plan`. Deep validation is
  internal analysis, not launch, but a clean plan is not a TrustOS or workspace
  clearance.
- Governor disagreements. Three plan rules sit on top of the governor's
  decision and are named in each target's `governor.plan_overlays`:
  `budget_approval_threshold`, `trustos_hold`, and `learning_history_bound`.
  The governor reports `queue` for a target the plan overlays. The governor's
  own budget check records the approval threshold but does not enforce it, so
  the fix belongs in `evaluation/companyos/resource_execution_governor.py`,
  which this work does not change. The overlays are the plan's workaround until
  that change lands.
- The `safety` block's zero counts (executor invocations, registry writes,
  stage transitions, Obsidian writes) and `network_calls: false` are design
  guarantees, not runtime measurements. Tests that forbid those calls enforce
  them.
- Live supplier, marketplace, or ad evidence. All evidence is caller-supplied.

## Known limits

- The plan is advisory and is not enforced by `run_validation_sprint` (see the
  note at the top). The handoff cannot bind an explicit run to this plan:
  `run_validation_sprint` does not accept a plan id and recomputes from live
  registries. A plan that goes stale (a new kill, a changed budget) can still be
  run by a caller who ignores it. Closing this needs a change to the execution
  path, which is out of scope here.
- Two learning-event checks duplicate the ledger's own vocabulary checks. They
  stay for a clearer error message.
- The planner's `_digest` and `_unit` helpers repeat patterns that other modules
  define. They are not yet shared.
- `unit_economics` is excluded by the existing service contract for the
  `product` department, so its missing-input branch is exercised with a
  monkeypatched service plan, not with live contract data.
- The existing run path still builds its evidence pool workspace-wide and
  without candidate scoping. The plan's candidate-scoped evidence and preview do
  not change that path.
- `stable_sprint_id` in `validation_sprint.py` is not stable (it includes
  `time.time_ns()`). It is unchanged, because it belongs to the execution path.
- Learning constraints and evidence come only from the caller. The plan adds no
  persistence.
