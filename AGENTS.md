# AI Development Policy

- Use the smallest sufficient context: inspect symbols and direct references before full files.
- Search for existing equivalent functionality before creating a module.
- Use architecture tools only for architecture work, current documentation tools only for external APIs, and bounded repository snapshots only for external-repository evaluation.
- Do not install MCP servers or skills globally.
- Do not enable live external actions without approval and safety gates.
- Distinguish implemented, tested, dry-run, integration-tested, and live-validated capability.
- CompanyOS outputs are offline planning records: never infer spend, outreach, publishing, payment, order, or platform authority from a scorecard, budget, deal, or draft.
- CompanyOS Approval Ledger is the canonical pre-integration gate: external actions remain blocked or simulation-only until a human-approved, evidence-backed policy exists.
- CompanyOS provider/credential work is metadata-only: never store secret values, real account IDs, `.env` contents, or live health results; link all future activation to the Approval Ledger.
- Update repository-specific AI memory after significant architecture changes.

## Token-efficient workflow

- Read `docs/ai/CANONICAL_ARCHITECTURE.md` and `docs/ai/CANONICAL_PATHS.md` before broad discovery.
- Use `scripts/ai/check_dev_stack.py` for capability checks and `scripts/ai/generate_session_handoff.py` at session boundaries.
- Run `scripts/ai/session_start.py --json` before editing and consult `docs/ai/PARALLEL_WORK_MATRIX.md` to avoid overlapping Claude-owned work.
- Run `scripts/ai/session_finish.py --dry-run` before committing; run the deterministic inference and commerce benchmarks when changing performance-sensitive paths.
- Before selecting a new Phase 1 feature, run `python scripts/phase1_readiness_report.py --json`; follow its single `next_best_action` unless the operator explicitly changes phase.
- When credentials are absent, prefer the offline marketplace and supplier-feasibility import layers for report value; never label fixture/manual supplier evidence as live proof.
- Consumer-attention imports are also offline/manual evidence: keep hooks, reviews, and creative signals separate from supplier proof and never turn them into ad/posting authority.
- Product Opportunity Synthesis is the canonical three-pillar decision layer; reuse existing scores and keep price, CPA, CTR, budget, and scale thresholds visibly labeled as planning assumptions.
- Filter large test and Semgrep logs with `scripts/ai/filter_test_output.py` and `scripts/ai/filter_semgrep_output.py`.
- Use architecture/dependency tooling only for architecture work; use current external documentation only for version-sensitive APIs.
- Do not install or enable third-party MCP servers, skills, models, or plugins without review.

## Codex operating rules

- Start with `git fetch origin`, `git switch main`, `git pull --ff-only origin main`,
  `git status --short`, and `gh pr list --state open`. Do not overlap an open
  PR's paths; create `codex/<outcome>` branches only after the scope is clear.
- Keep the canonical architecture intact: one event spine, one Commerce MVP
  path, existing provider clients, and no parallel orchestration/scoring.
- Treat network, credentials, provider calls, spending, publishing, orders,
  inventory, payments, and customer messages as default-off. State whether a
  result is fixture-tested, dry-run, integration-tested, or live-validated.
- Never stage `artifacts/`, `.env`, credentials, raw provider payloads, browser
  traces, cache files, or unrelated dirty-worktree changes. Stage explicit
  paths only.
- Use `scripts/ai/select_tests.py --from-git --json` before choosing tests and
  `scripts/ai/run_local_quality_gate.py --from-git --json` plus
  `scripts/ai/pr_readiness_report.py --json` before opening a PR. Run
  `session_finish.py --dry-run` and `git diff --check` before committing.
- Use `gh` for PR state/checks/merge only after local scope and safety review.
  Use web research only for version-sensitive external APIs; cite primary docs.
- Final reports lead with outcome and include scope, changed files, test commands
  and results, unrun checks, safety/no-mutation confirmation, risk/rollback,
  PR status, and the next single operator action.
- Launch Draft Pack outputs are client-facing drafts only. Keep Shopify/Medusa payloads at `status: draft`; never add publication, ad spend, order, payment, messaging, or provider mutation authority to this layer.
- Site Draft Builder outputs are platform-neutral blueprints only. Keep all platform payloads at `status: draft`; never add domain, hosting, CMS, analytics, publishing, or storefront mutation authority to this layer.
- CompanyOS registry outputs are contracts and decisions only. Treat agent, skill, tool, workflow, model, trace, eval, and knowledge entries as offline policy; never infer execution authority or enable live integrations from registry metadata.
- Intelligence adapter plans are contracts only. Keep Apify, DataForSEO, SerpApi, official APIs, and proxy providers in fixture/manual/dry-run or blocked mode; reject secrets/raw payloads and require Approval Ledger, credential, budget, terms/privacy, and output-contract gates before any future live adapter.
- The DataForSEO adapter is the first concrete provider-specific layer, but it remains fixture-backed and fail-closed. Treat normalized SERP/shopping signals as supplemental evidence only; never treat them as live validation, supplier proof, or launch authorization.
- TrustOS is the shared pre-launch control plane: keep Control/Evidence/Gate/Exception metadata separate from the Approval Ledger, use policy packs for security/privacy/legal/tax/AI/provider/public-launch checks, and keep scanners, professional conclusions, credentials, provider calls, and external actions disabled by default.
- Security scanner work must normalize sanitized fixture/output metadata through TrustOS; do not install or execute scanners, call GitHub/external services, read credentials, or commit raw findings, secrets, HTML, exploit payloads, or client data.
