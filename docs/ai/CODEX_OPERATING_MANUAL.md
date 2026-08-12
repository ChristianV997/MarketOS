# MarketOS Codex Operating Manual

## One task, one gate, one outcome

Choose one concrete task that clears the highest unblocked gate. Start with
`session_start`, current `main`, and open PR inspection. Use Codex for local
implementation, deterministic tooling, targeted tests, and PR hygiene; use
Claude only when an already-coordinated parallel research/design task benefits
from it. Never run parallel agents over the same paths.

High-quality work is additive, bounded, tested, and explicit about whether it
is fixture-tested, dry-run, integration-tested, or live-validated. It reuses
the canonical event spine and existing Commerce MVP/evaluation paths.

## Fast loop

1. `python scripts/ai/session_start.py --json`
2. `python scripts/phase1_readiness_report.py --json`
3. `python scripts/ai/phase_gate.py --from-git --json`
4. `python scripts/ai/run_local_quality_gate.py --from-git --json`
5. Make the smallest outcome-driven change that clears the readiness report's single next action.
6. Run selected tests, then `session_finish.py --dry-run` and `git diff --check`.
7. Run `pr_readiness_report.py --json`; stage explicit files; open a draft PR.

`run_local_quality_gate.py` composes the planner, PR readiness, focused-test,
phase-gate, and CI-lane tools without network or GitHub API calls. `clear`
means no changed files; `advisory` means run the recommended focused checks;
`blocked` means remove a secret/artifact or resolve the named phase gate.

Do not use this loop to bypass a phase gate. Credentials, artifacts, raw
payloads, provider writes, and mutation authority remain outside normal runs.

For consulting evidence, treat marketplace, supplier, and consumer-attention
reports as separate inputs. Consumer attention can produce deterministic hooks,
pain points, objections, and creative hypotheses, but it is never supplier
proof and never grants permission to post or buy ads.

The synthesis/report-v2 layer is the preferred commercial deliverable after
the three offline evidence pillars. Reuse its existing scores; do not create a
parallel ranking or promise launch readiness from fixture/manual evidence.
* Treat `scripts/generate_launch_draft_pack.py` as an offline presentation command. Verify every output is draft-only and never add a provider call to make a launch asset look more complete.
* Treat `scripts/generate_site_draft_pack.py` as a portable planning command. Do not migrate stacks, install dependencies, publish routes, or mutate domains/platforms.
## CompanyOS operating check

For internal operating work, run `python scripts/run_companyos_department_layer.py --markdown`. Treat Finance as scenario planning, Accounting as ledger-ready seed data, and Sales as consent-aware drafts. Keep the approval queue and risk register in the final report.

For agent architecture work, run `python scripts/run_companyos_registry_layer.py --markdown`. Treat registries as contracts and decisions, not installed integrations. Check tool risk, model budgets, trace/eval requirements, knowledge privacy, and workflow interrupts before proposing live adapters.

For external-action planning, run `python scripts/run_companyos_approval_ledger.py --markdown`. Treat scopes, conditions, budget caps, simulations, and audit events as control records; never treat a draft or simulated approval as execution authority.

For provider planning, run `python scripts/run_companyos_provider_registry.py --markdown`. Store references and placeholders only; never read, print, validate, or write credential values.
For intelligence adapter planning, run `python scripts/run_intelligence_adapter_plan.py --markdown`. Treat request envelopes and normalized records as dry-run contracts; never turn them into provider calls without a separate approval-gated implementation.

For the DataForSEO adapter, run `python scripts/run_dataforseo_readonly_adapter.py --markdown`. It is a deterministic fixture parser and commerce-context bridge, not a credential checker or live search transport. Reject raw payload/HTML inputs and preserve all cost, terms/privacy, and Approval Ledger blockers.

For scanner evidence, keep normalization fixture-backed and fail-closed. Do not
install scanners, invoke external services, or expose raw reports.
# TrustOS operating note

TrustOS is metadata-only: controls state requirements, evidence records state
what is missing, gates fail closed, and exceptions route to a human or
professional. Do not run scanners, read credentials, call providers, expose
internal prompts, or treat readiness as authorization.

The security scanner adapter is fixture/output normalization only. Do not install
or execute scanners, call GitHub, read credentials, or commit raw findings,
secrets, HTML, exploit payloads, or client data.

Security CI Gate permits only explicit, allowlisted, bounded local execution.
Default to `--plan-only` or fixture ingestion; never add shell execution,
network access, credentials, uploads, or raw scanner artifact persistence.
# Client workspace rule

Treat client workspaces as curated projections, never source-code forks or unrestricted copies. Run the offline leakage checker and TrustOS gates before any client-safe export; future auth, database, and RLS implementation must preserve this boundary.

Route proposed execution through the Resource & Execution Governor. Treat budgets, quotas, portfolio caps, kill/scale rules, retry limits, and learning capture as mandatory safety metadata.
