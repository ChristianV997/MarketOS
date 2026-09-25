# Mainline Vertical Acceptance

Status: implemented on refreshed `origin/main` and intentionally offline.

The acceptance command is a bounded witness for the verticals that are
actually merged into MarketOS mainline. It does not assemble an alternate
commerce workflow, calculate a second set of economics, mint a second event
schema, or become a client-export authority.

## Command

Run from a clean MarketOS checkout:

```text
python scripts/ai/run_mainline_vertical_acceptance.py --json
```

For a short operator summary:

```text
python scripts/ai/run_mainline_vertical_acceptance.py --markdown
```

The command returns exit code `0` only when the merged mainline checks pass.
It returns exit code `1` for a failed or malformed in-scope contract. An
upstream authority that is not present on mainline is reported as
`unavailable`; it is never silently treated as a pass and does not cause the
runner to import an unmerged PR.

The report includes `head_sha`, `origin_main_sha`, and `merge_base`. A
mainline acceptance result is only comparable when these refs are refreshed.
The runner also requires a clean Git worktree, including no untracked files. If
that status is dirty or unavailable, it returns `blocked` before any merged
authority runs; downstream checks remain `not_run`. A PR or detached worktree
is reported as `blocked` before replay, dogfood, or export authorities are
invoked and cannot claim mainline acceptance; the system-test contract is
not applicable there until it runs on exact refreshed `origin/main`.

## Authority Graph

The command composes these existing authorities:

```text
research_to_decision.load_manifest/build_research_to_decision
  -> run_commercial_replay_integration.run_scenarios
     -> canonical Decimal economics kernel
     -> dry-run lifecycle and promotion gate
     -> canonical Event projections and replay certification
     -> fulfillment risk lifecycle and RMA projection
     -> InMemoryEventRepository append/replay
     -> TrustOS export_client_evidence
  -> run_operator_dogfood_workflow.trustos_export
```

The acceptance code reads these results and checks their contract fields. It
does not copy formulas, event hash code, promotion rules, redaction rules, or
workspace registry logic.

The direct service check uses the existing service economics adapter exposed
by the replay runner. It proves that insufficient service inputs produce
`data_inadequate` with no economics and that adequate fixture inputs produce
the existing client-service-ready adapter status. It is not a replacement for
the service-delivery producer or route.

## Mainline Scope

The refreshed mainline used by the acceptance harness contains the merged
replay and operator dogfood behavior:

- `scripts/run_commercial_replay_integration.py` from merged PR #279;
- `scripts/operator_dogfood_vertical.py` and
  `scripts/run_operator_dogfood_workflow.py` from merged PR #283;
- the canonical economics, event, fulfillment, workspace, registry, and
  TrustOS modules used by those paths.

The service-delivery route and producer associated with PRs #271 and #275 are
not present on this mainline. The report therefore emits:

```json
{
  "status": "unavailable",
  "reason": "service_delivery_authority_not_merged_on_mainline",
  "source_prs": [271, 275]
}
```

The missing paths are enumerated so an operator can distinguish an absent
authority from a failing merged authority. This harness never imports a PR
worktree or a branch to make that path appear available.

## Acceptance Matrix

### Candidate and template identity

The replay scenarios use candidate IDs from the normalized research result.
The scenario template is selected through the explicit template argument.
The harness runs the real operator vertical with a synthetic candidate ID and
an unrelated display label. The acceptance requires:

- the selected candidate ID to remain the ID supplied to the replay;
- the selected template to remain the explicit template;
- the display label not to route the candidate;
- `live_validated` and `launch_authorized` to remain `false`.

This is provenance coverage, not candidate ranking or launch authorization.

### Missing and explicit zero economics

The missing-cost probe runs the public replay CLI against the fixture with no
supplier offer. It requires:

- the unit-economics step to be `unavailable`;
- the economics evidence state to be `missing`;
- `product_cost` and `supplier_shipping` to be named missing inputs;
- contribution values not to appear in the economics detail, packet, or
  downstream client export;
- promotion and launch authorization to remain blocked.

The explicit-zero probe makes a temporary copy of the existing fixture import,
sets the supplied shipping amount to numeric zero, and deletes the copy after
the CLI returns. It requires the canonical replay to keep zero as a supplied
fixture amount, not add it to the missing set, and calculate the economics
step. The representation may be `0`, `0.0`, or another Decimal-preserving
string; acceptance compares its numeric value, not its formatting.

This distinction is intentional. The canonical kernel may expose zero-valued
fallback fields together with missing inputs. The replay adapter is the
authority that removes missing-input economics from the published lifecycle
packet. The acceptance checks the serialized boundary rather than treating an
internal placeholder as observed cost.

### Currency and evidence

The currency probe sends the existing USD supplier record through the existing
research-to-decision builder against its MXN lane. The expected result is the
canonical `ResearchToDecisionError` mismatch path. No exchange rate is
inferred by the harness.

Each replay row must preserve:

- research input: `fixture`;
- commerce and fulfillment lifecycle: `simulated_or_planned`;
- calculation execution: `actual_executed` only for the local calculation;
- external validation: `unavailable`;
- CI: `ci_unavailable`;
- TrustOS export execution: `actual_executed`, with an export evidence state
  of `requires_review`.

Fixture and simulated evidence never become `live_validated`, authoritative
supplier proof, payment proof, commercial validation, or launch authorization.

### Compliance

Mainline does not provide authoritative compliance evidence for these fixture
scenarios. The acceptance requires the existing compliance result to keep its
gate false and `live_lookup_performed` false. The report describes this as
`not_assessed` in the acceptance explanation while preserving the runtime
value `unavailable`; no new compliance status vocabulary is added to the
production authority.

### Event scopes and replay identity

The canonical replay row contains two event aggregates:

- `commerce_dry_run`: 17 events, consisting of start, the 15 lifecycle
  steps, and completion;
- `commerce_fulfillment_risk`: 20 events, consisting of start, the 18
  fulfillment states, and completion.

The full row contains 37 events. Acceptance requires:

- unique event IDs;
- 37 canonical event replay hashes matching the replay summary sequence;
- 64-character SHA-256 hash values;
- a stable row-level replay hash;
- equal repeated replay output from the existing runner;
- 37 first appends and 37 idempotent second appends;
- no event sequence issue or live-authority violation.

The direct commerce-scope probe checks the 17-event projection separately.
It does not modify or reimplement `Event.replay_hash`.

### Fulfillment and reconciliation

The 20-event projection is accepted only as simulated fulfillment/RMA and
contribution reconciliation. It remains non-authoritative and cannot enable a
supplier order, shipment, refund, message, or payment. The full replay row
must continue to carry `launch_authorized: false`, no external mutations, and
no provider, credential, or database activity.

### TrustOS-safe export

The acceptance invokes the existing `export_client_evidence` boundary in a
temporary registered workspace and invokes the merged dogfood bridge's
`trustos_export` projection. It requires:

- registered workspace identity;
- workspace ID agreement between the authority and payload;
- allowed client-safe fields only;
- bounded payload size;
- `validated_no_sensitive_fields` redaction status;
- `requires_review` evidence state;
- rejection of an internal-prompt-shaped payload;
- rejection of a cross-workspace payload.

The export function is reject-only. It does not scrub unsafe content into a
safe-looking result. The acceptance never includes raw internal prompts,
source code, credentials, provider payloads, client data, or filesystem paths
in its report.

## Safety Contract

The command and tests use only local fixture data and temporary directories.
They do not:

- read credentials or `.env` files;
- call suppliers, providers, models, or external APIs;
- create orders, payments, refunds, ads, messages, or publications;
- write a database or persistent artifact;
- mutate a workspace registry outside a temporary directory;
- claim fixture execution is live validation.

The report's `safety` object is explicit. Its mutation, network, provider,
credential, payment, order, advertising, publishing, database, and messaging
flags must remain `false`. The `ci` field remains `ci_unavailable` unless an
independently executed CI job supplies admissible evidence; a zero-step or
runnerless job is not a pass.

The full operator dogfood wrapper has a state-collision guard. Because this
acceptance file is itself an uncommitted owned path during local execution,
the harness does not weaken that guard or pretend the full wrapper ran. It
reuses the already-validated replay projection and invokes the merged
dogfood TrustOS export phase directly. The report records this as a bounded
guard note.

## Validation

Focused validation for this surface:

```text
python -m pytest -q tests/system/test_mainline_vertical_acceptance.py
python -m compileall -q scripts/ai/run_mainline_vertical_acceptance.py tests/system/test_mainline_vertical_acceptance.py
python -m ruff check scripts/ai/run_mainline_vertical_acceptance.py tests/system/test_mainline_vertical_acceptance.py
git diff --check
```

Adjacent merged-authority validation:

```text
python -m pytest -q tests/system/test_commercial_dry_run_replay_integration.py tests/test_operator_dogfood_vertical.py tests/test_operator_dogfood_workflow.py
python -m pytest -q tests/contracts/test_canonical_event_contract.py tests/contracts/test_event_repository_contract.py tests/contracts/test_replay_certification.py tests/commerce_canonical/test_kernel_integration.py
```

The system test uses the real current functions and CLIs through the new
acceptance runner. It does not mock the canonical replay, economics, event,
or TrustOS authorities. The negative inputs are synthetic temporary copies
and are deleted before the report returns.

## Limitations

This is an acceptance witness for merged offline behavior. It is not:

- a supplier verification;
- a compliance certification;
- a live market observation;
- a payment, order, fulfillment, or refund integration;
- a tenant authentication or authorization system;
- evidence that the #271/#275 service-delivery route is available;
- GitHub Actions CI evidence.

If the service-delivery route is merged later, the next acceptance run should
refresh `origin/main`, rerun the file-presence check, and add that authority's
focused contract without importing its PR branch early.
