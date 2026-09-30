# Owner dashboard (`/owner`)

The owner's own discovery and portfolio view: ranked opportunities, evidence quality and gaps, planning
economics with labelled assumptions, and performance only when real records exist. MarketOS recommends and
explains; Shopify remains the commerce execution authority. Everything here is advisory.

## Data source: demo fixture only

The page currently reads `sources/fixtureSource.ts`, which returns bundled demo data and makes no request.
The fixture is real output of the offline discovery service (`services.opportunity_discovery.run_discovery`,
`compare` mode, run in-process); regenerate it with `fixtures/generate_owner_demo_run.py`. It is **not** an API
response, not live, and not the owner's portfolio. The UI says so.

A live source must not be added until an authorized, workspace-scoped read endpoint exists: identity verified
and the workspace resolved on the server, never a client-supplied workspace. Today no read endpoint for
discovery runs exists on `main`, and the frontend API client sends no identity or workspace.

## Provider mapping (done once, in `lib/adaptDiscoveryRun.ts`)

Provider: `DiscoveryRun.to_dict()` from `services/opportunity_discovery/service.py`. Behaviours preserved:

- `ranked_candidate_ids` lists only ready, scored candidates. Others are shown as "Not ranked" with a reason.
  Ranks are the provider's order; nothing is re-sorted or re-scored, and no grade is shown (none is provided).
- Evidence gaps come from `decisions[].evidence_gaps`. The events API's `OpportunityScoreView` has no
  `evidence_gaps` field (it has `unknowns` and `blockers`), so the two providers name the concept differently.
- Money is a decimal string. `"unknown"`, empty and null are missing, never zero.
- When a scenario lists `missing_inputs`, the provider fills those inputs with a zero of unknown basis. Those
  placeholder lines and every total built on them are shown as "Not available"; real supplied zeros stay.
- `synthesis.recommendation` can say "advance to launch draft" for a candidate that is not research-ready.
  It is never the headline, and the UI says the evidence status takes precedence.

## Not implemented (by design)

Save to portfolio (disabled, "not connected"), any Shopify/ad/publish/order/payment/inventory action, any
provider call, and any economics arithmetic in the browser.

## Tests

`frontend/tests/owner-dashboard.model.test.mjs` (adapter, composer, helpers, static safety scan) and
`frontend/tests/owner-dashboard.components.test.mjs` (rendered components queried by role and accessible
name; helpers in `frontend/tests/helpers/`). Both are fixture-tested, not API-tested.
