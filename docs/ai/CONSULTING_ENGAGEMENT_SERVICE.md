# Consulting Engagement Service

## Purpose

`services.consulting_engagement` is the deterministic, offline composition
boundary for a client consulting engagement. It assembles an engagement
request, existing component-report references, evidence status, capability
availability, blockers, and a client-safe projection. It does not introduce a
new scorer, economics calculator, promotion gate, replay engine, event schema,
provider client, or TrustOS authority.

The service is planning and delivery support only. A successful local run is a
fixture/manual or dry-run result, not supplier proof, legal clearance, live
validation, launch authorization, or evidence of a commercial transaction.

## Public Contract

Use `build_consulting_engagement(request, workspace=..., artifact_store=...)` with a
`ConsultingEngagementRequest` or a mapping accepted by
`ConsultingEngagementRequest.from_mapping`. The request contains:

- client and registered workspace identity;
- client objective, geography, language, and scope;
- `product`, `service`, `hybrid`, or `unknown` offering kind;
- selected deliverables and optional upsell recommendations;
- typed evidence inputs with class, state, source reference, timestamp, and
  authority flag;
- assumptions, conflicts, missing information, and existing component report
  IDs.

The result is a `ConsultingEngagementResult` with deterministic status,
blockers, next action, execution-plan metadata, component report references,
client-safe projection, TrustOS export, stable fingerprint, and explicit
`read_only`, `network_calls`, `database_writes`, and `mutated` flags.

## Authority Graph

The composition follows existing authorities rather than replacing them:

```text
request mapping
  -> WorkspaceRegistry + ClientWorkspace identity
  -> ArtifactStore canonical path validation (no write)
  -> ReportRegistry component references (workspace-bound)
  -> ServiceContractRegistry capability planning
  -> existing CompanyOS service engagement shape
  -> CommercialRunEnvelope dry-run identity
  -> TrustOS export_client_evidence allowlist
```

The orchestrator never accepts a raw workspace ID as authority. The caller
supplies the already workspace-bound `ArtifactStore`; the orchestrator checks
that its bound workspace matches the registered identity before path
validation. The supplied
`ClientWorkspace` must be registered and must exactly match the request's
workspace identity. Component reports from another workspace are rejected.
TrustOS receives only its existing safe fields: workspace, status, blockers,
evidence required, approvals required, and next actions.

## Evidence Semantics

Evidence class and evidence state remain separate:

- `fixture`, `manual`, `manual_import`, `simulated`, `simulated_or_planned`,
  `planned`, and `derived` remain below live proof;
- `missing`, `stale`, `conflicting`, `blocked`, and `unavailable` states create
  deterministic blockers and never become zero-filled evidence;
- only an explicitly `live`, `available`, authoritative input is summarized as
  live authoritative evidence;
- even that summary does not grant launch authorization or external-action
  authority;
- `unknown` offering kind is supported as an input but fails closed until the
  offering kind is confirmed; explicit deliverables do not create an execution
  plan while the offering kind is unknown.

The service does not infer supplier proof, customer authorization, economics,
compliance status, or legal clearance from attention, market, fixture, or
manual inputs. Geography and language are planning metadata; they are not a
jurisdictional approval.

## Determinism and Safety

The engagement ID is derived from the canonical request fingerprint. The
fingerprint includes normalized typed inputs, evidence class/state, and
assumptions, so repeated equivalent requests produce equivalent JSON and
Markdown. The Markdown report is a human-readable planning projection and
contains no raw component findings, module paths, prompts, credentials, or
provider payloads.

Optional capabilities degrade to an `unavailable` plan item and a blocker. The
service does not import or execute an optional provider as a fallback. All
production orchestration is read-only, network-free, and mutation-free; test
fixtures use temporary workspace state only.

## Local Validation

From a clean MarketOS worktree, use the bounded checks below:

```text
python scripts/ai/session_start.py --json
python scripts/ai/check_dev_stack.py --json
python scripts/ai/select_tests.py --from-git --json
python -m pytest -q tests/services/test_consulting_engagement
python -m pytest -q tests/contracts/test_architecture_boundaries.py
python -m compileall -q backend api evaluation services scripts tests
python -m ruff check services/consulting_engagement tests/services/test_consulting_engagement
git diff --check
python scripts/ai/session_finish.py --dry-run
python scripts/ai/run_local_quality_gate.py --from-git --json
python scripts/ai/pr_readiness_report.py --json
```

These are local or dry-run checks. GitHub Actions evidence must be classified
separately, and a runnerless or zero-step job is unavailable CI evidence rather
than a pass.

## Limitations and Rollback

This vertical does not implement authentication, tenant authorization,
database persistence, RLS, provider activation, payment, order, publishing, or
launch control. Those decisions remain with their existing authorities and
approval gates. Rollback is the single commit that introduces this directory,
its fixtures/tests, and this document; reverting that commit removes the
composition surface without changing the reused authorities.
