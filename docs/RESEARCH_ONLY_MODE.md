# MarketOS Research-Only Operating Mode

MarketOS is currently restricted to bounded market research and simulation.
Discovery, supplier quotes, landed-cost validation, audience hypotheses,
competitor evidence, experiment matrices, portfolio scoring, and reports may
run. Brand creation, inventory creation, landing pages, social accounts, ad
publishing, orders, fulfillment, and live budget changes may not run.

## Runtime controls

Set `MARKETOS_RESEARCH_ONLY=true` before starting the API, orchestrator, or
research worker. `SidecarContext.require_live_idempotency()` and the major
raw provider clients consult the same central policy in
`backend/research/mode.py`.

The safe entrypoints are:

```powershell
$env:MARKETOS_RESEARCH_ONLY = "true"
.\scripts\research\Start-MarketOSResearch.ps1 -Category fitness -Once
python scripts/research/run_category_research.py fitness --max-products 20 --json
```

For continuous operation, omit `-Once`. The worker obtains
`state/research.lease`; a second PC/AWS worker exits rather than concurrently
writing JSON state. The lease is local-state safe; a shared S3/Dynamo/Postgres
lease must be configured before running active writers on separate machines.

## Durable outputs

Research writes only local, atomic artifacts under `state/`:

- `research_cache.json` — bounded source cache and health statistics
- `research_dossiers.json` — category dossier and approval requests
- `research_reports/<category-id>.json` — machine-readable report
- `research_reports/<category-id>.md` — human-review report

Ollama enrichment is opt-in with `MARKETOS_RESEARCH_OLLAMA=true`. It can add
untrusted summaries, hypotheses, and questions; it cannot approve or launch.

## Launch boundary

The eventual first small launch requires approved requests for `brand`,
`inventory`, `landing_page`, `social_account`, and `ads`, plus credentials,
budget, and a `candidate` tipping-point result. The gate is implemented in
`services/product_research/launch_gate.py`; it remains blocked while
research-only is enabled.
