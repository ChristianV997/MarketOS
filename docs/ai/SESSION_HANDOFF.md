# Session Handoff
Date: 2026-08-01
Repository: C:\Users\HP\Documents\MarketOS-research-ops
Branch: codex/marketos-research-ops
Commit: 01ddf80 (research-only runtime); handoff refresh pending
Objective: Restrict MarketOS to bounded commerce research and build the dossier/report/approval path.

## Files changed
- `backend/research/mode.py`, `cache.py`, `lease.py`, `ollama.py`
- `services/product_research/dossiers.py`, `dossier_store.py`, `run.py`, `portfolio.py`, `launch_gate.py`, report exports
- Research-only guards in API, orchestrator, commerce launch/checkout/fulfillment, Meta/TikTok/AJO/Postiz/affiliate/supplier paths
- `scripts/research/*` PowerShell and Python supervisor/CLI entrypoints
- `docs/RESEARCH_ONLY_MODE.md`, `.env.example`, `docs/ai/COMMANDS.md`
- `tests/test_research_ops.py`

## Interfaces affected
- `MARKETOS_RESEARCH_ONLY=true` blocks non-dry-run external mutations.
- `SidecarContext.require_live_idempotency()` now consults the central mode gate.
- New `POST /api/services/category-research` and research approval request/decision routes.
- New `ResearchRunConfig`/`run_category_research`, `CategoryDossier`, `ProductDossier`, supplier/evidence contracts.
- No live launch path was enabled; the launch gate requires research evidence plus five human approvals.

## Tests run
- Focused research/product/commercial suite: 20 passed.
- Research safety suite after approval additions: 6 passed.
- Broader compatibility set: 46 passed, 4 skipped.
- Full suite: 2649 passed, 9 skipped, 11 failures from missing optional local dependencies and an existing numerical shadow-validator test; see final report.
- `python -m compileall -q backend services orchestrator scripts/research`: passed.
- Semgrep policy at error severity: 0 findings.
- PowerShell one-shot supervisor smoke test: passed; generated a research-only dossier and Markdown/JSON report.

## Results
- Research worker produces bounded, deduplicated category dossiers with source provenance, supplier quotes, shipping/landed-cost fields, source cache/health, audience hypotheses, competitor evidence, experiment cells, related top-three portfolio selection, pessimistic/base/optimistic simulations, and tipping-point scoring.
- Reports are written atomically under `state/research_reports/`; cache/dossiers/approvals use atomic JSON persistence.
- Single-writer lease prevents two workers sharing a local state directory from writing concurrently.
- Ollama enrichment is optional (`MARKETOS_RESEARCH_OLLAMA=true`) and limited to untrusted summaries/hypotheses/questions.

## Decisions made
- Keep existing discovery, supplier, validator, audit, and report infrastructure; compose it instead of adding duplicate engines.
- Research-only is enabled by the PowerShell supervisor and documented in `docs/RESEARCH_ONLY_MODE.md`; the Python library default remains backward-compatible for existing unit tests.
- No Postgres/S3/Dynamo shared writer was invented; a real PC/AWS shared lease/state backend remains a deployment follow-up.

## Risks
- The full suite still reports 11 environment/baseline failures: missing `prometheus_client`, `trendspyg`, `sentry_sdk`, optional Firecrawl assumptions, and an existing shadow-validator array/constant-input issue.
- External discovery sources returned 403/404 in the smoke run and therefore produced honest fallback/mock evidence; reports retain source health rather than treating it as live evidence.
- The five-part launch approval gate is implemented but has no authentication layer yet; do not use the decision route as a substitute for operator identity/access control.

## Remaining blockers
- Configure approved real research sources and credentials, then run repeated category passes to accumulate evidence.
- Decide and implement the shared AWS lease/state backend before enabling a second active machine.
- Resolve the 11 baseline environment/test failures in a separate dependency/tooling phase.
- Do not enable live creation or launch until a category dossier is `candidate`, all five approval types are approved, credentials and budget checks pass, and the operator explicitly requests the launch.

## Next action
Review `state/research_reports/<category-id>.md` and run:
`$env:MARKETOS_RESEARCH_ONLY="true"; .\scripts\research\Start-MarketOSResearch.ps1 -Category <category> -Once -MaxProducts 20`

## What the next agent should inspect first
1. `docs/RESEARCH_ONLY_MODE.md`
2. `backend/research/mode.py`
3. `services/product_research/run.py` and `services/product_research/dossiers.py`
4. `state/research_reports/` and `state/research_cache.json` (local, ignored)
5. `git fetch origin; git diff origin/codex/marketos-research-ops` before editing
