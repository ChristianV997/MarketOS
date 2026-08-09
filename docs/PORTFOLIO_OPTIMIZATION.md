# Portfolio Optimization

MarketOS portfolio optimization is a deterministic planning simulator. It ranks safe research actions—evidence acquisition, refinement, pipeline refresh, validation, calibration, deliverable generation, risk resolution, and executive review—under simulated budget and time constraints.

## Safety model

Budget and cost fields are estimates only. They never allocate capital, create spending authority, call providers, place orders, publish, message customers, or mutate commerce systems. Action payloads point only to local/manual/cache-only endpoints or are advisory.

## Scenarios

The default plan evaluates `$0 / 2 hours`, `$100 / 4 hours`, `$500 / 1 day`, `$1,000 / 2 days`, `$5,000 / 1 week`, `$10,000 / 2 weeks`, risk-reduction, and fastest-progress scenarios. Selection is deterministic and bounded by budget, hours, action count, blocked actions, and safe prerequisite order.

## Workflow and API

Generate actions with `POST /api/optimization/actions/generate`, build a plan with `POST /api/optimization/portfolio`, or run a standalone scenario with `POST /api/optimization/scenario`. The workflow orchestrator includes `portfolio_optimization` before its final summary and supports `portfolio_optimization_cycle`.

## Interpretation

Information gain, confidence delta, and risk reduction are planning heuristics derived from persisted evidence gaps, opportunity stages, calibration, and validation state. They are not ROI, demand, profit, ROAS, or investment claims. Review evidence limitations before any subsequent manual action.
