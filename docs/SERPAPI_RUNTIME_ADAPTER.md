# SerpApi runtime adapter (v1)

The second concrete provider runtime bridge after DataForSEO
(`backend/adapters/research/dataforseo.py`), following the exact same
seam and safety conventions.

## Provider purpose

SerpApi is a bounded search/SERP intelligence candidate for
`search_serp_keyword_demand` / `competitor_pricing` data needs — the same
capability gap DataForSEO addresses. MarketOS's own existing planning
layer (`evaluation/companyos/subscription_registry.py`) explicitly
presents DataForSEO and SerpApi as **consolidation choices, not
simultaneous purchases**: "choose one search provider after a bounded
benchmark." This adapter exists so that benchmark can eventually be run
through the same runtime seam DataForSEO already uses, without
committing to either provider today.

## Why no new offline module was built

Unlike DataForSEO, which has its own dedicated offline parser module
(`evaluation/commerce/dataforseo_adapter.py`), SerpApi's offline plan
already lives entirely inside the generic, provider-agnostic
`evaluation/commerce/intelligence_adapter_plan.py` module — its own
`_PROVIDER_SPECS` entry, `build_intelligence_adapter_plan()`, and
`parse_dry_run_fixture()`, already covered by that module's own
parametrized test suite (`tests/test_intelligence_adapter_plan.py`).
Building a second, SerpApi-specific offline parser would duplicate a
capability the generic module already provides. `backend/adapters/
research/serpapi.py` delegates to that existing generic machinery
instead — no new provider registry, adapter framework, or parser is
introduced.

## Two bounded request kinds

- **`"organic_search_snapshot"`** (default, primary, required) — organic
  SERP/keyword-demand signals, `SearchDemandEvidence`, its own sanitized
  fixture added by this PR
  (`tests/fixtures/intelligence_adapter_plan/serpapi_organic_snapshot_dry_run.json`,
  fields: `candidate_id`, `query`, `title`, `rank`, `trend_label` — no
  price/rating, appropriately absent for organic results).
- **`"shopping_snapshot"`** (optional, secondary) — competitor-pricing
  signals, `CompetitorPricingEvidence`, reusing the one fixture that
  existed before this PR
  (`tests/fixtures/intelligence_adapter_plan/serpapi_shopping_snapshot_dry_run.json`).

Both are parsed by the same existing, generic `parse_dry_run_fixture()` —
neither introduces a new parser or evidence type.

## Dry-run-only status

`mode="plan_only"` via `SidecarContext.dry_run=True` (the default) is the
only reachable path. `fetch_search_evidence()`/`discover()` parse the
bundled sanitized fixture for the requested `request_kind` (substituting
the caller's own query into its records) or a caller-supplied fixture
payload — never a live SerpApi request. A `context.dry_run=False` request
never reaches the offline plan/parser; it returns a structured
`blocked_live_mode` result naming every unmet prerequisite.

## Provider Registry check

`evaluation/commerce/intelligence_adapter_plan.py` imports
`build_provider_registry` but never actually calls it — this adapter does
not inherit that gap. `fetch_search_evidence()` checks Provider Registry
membership explicitly (`provider_registered` field on every result); if
`serpapi` were ever absent from the registry, `provider_not_registered`
is added to `blockers` and the result is forced to `status="blocked"`,
never silently treated as ready.

## Safety boundary

- No network, credential, model, provider, SDK, or plugin call occurs
  anywhere in this file (verified by an AST-based import check).
- Any unexpected failure from the offline plan/parser is caught and
  converted to a safe, generic `status="error"` result — the raw
  exception message is never included in the returned evidence
  (verified by a regression test injecting a secret-shaped exception
  message).
- Every result carries `evidence_tier="supplemental_non_live"` and
  `retry_attempts_allowed=0` — no live transport exists, so no retry
  logic exists either; this is an explicit, testable zero.
- `NormalizedEvidenceRecord.__post_init__` (in the reused generic module)
  already rejects secret-like normalized fields at construction time —
  this adapter inherits that guarantee rather than re-implementing it.
- `ProviderRequestPlan.__post_init__` and `ProviderRunEnvelope
  .__post_init__` (also reused) already raise if `live_request_created`
  is `True` or scheduling/network/raw-payload flags are set — the same
  fail-closed-by-construction pattern DataForSEO's offline module uses.

## Future activation requirements

Identical prerequisite list to DataForSEO's, reusing the same Approval
Ledger/Credential Registry vocabulary: an approved Approval Ledger
request (`provider_call` + `web_data_acquisition`), a configured
`credential-serpapi` reference (secret value never loaded here), an
approved budget cap, complete terms review, complete privacy review,
passing output-contract tests against real (not fixture) responses, a
defined timeout/retry policy, workspace/client-isolation checks, and a
separately reviewed live transport implementation (none exists in this
release).

## Evidence limitations

`evaluation/commerce/intelligence_adapter_plan.py`'s own SerpApi request
plan (`endpoint_placeholder="search.json"`,
`engine_placeholder="google_shopping"`) is explicitly documented there as
a planning placeholder, not a confirmed live SerpApi API contract —
nothing in this adapter changes that or claims otherwise. Every
normalized record is fixture/dry-run sourced and explicitly labelled
`supplemental_non_live`; it is not live search proof, not launch
authorization, and not evidence of demand.

## No-network default

Confirmed by `test_module_imports_no_network_or_sdk_modules` (AST-based,
mirrors the same check in `tests/test_dataforseo_research_adapter.py`)
and by every test in `tests/test_serpapi_research_adapter.py` running
fully offline against the bundled or a caller-supplied fixture.
