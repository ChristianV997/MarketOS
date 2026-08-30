# DataForSEO runtime adapter (v1)

This is the first concrete *runtime* seam for DataForSEO, sitting directly
on top of the existing offline planning layer
(`evaluation/commerce/dataforseo_adapter.py`, merged in PR #178). It adds
one new file, `backend/adapters/research/dataforseo.py`, and introduces no
new evidence dataclass hierarchy, no new event type, no new provider
registry, no new protocol, and no live transport.

## Why a runtime adapter, and why now

The offline module already has a complete, tested request-plan/parser/
evidence contract (157 deterministic tests). What was missing was a bridge
from that offline module into MarketOS's actual Product Research
Intelligence Engine (`backend/mvp_commerce/product_research.py`) — the
place a future caller would actually attach DataForSEO evidence to a
research candidate. This PR adds exactly that bridge, nothing else.

## Runtime seam

`backend/adapters/research/dataforseo.py` follows the one existing
precedent for a concrete research-evidence source in this directory,
`backend.adapters.research.cj_public_evidence`: plain sync free functions
(`health()`, `fetch_search_evidence()`, `discover_search_queries()`), not a
class registered against `backend.adapters.research.registry
.ResearchAdapterRegistry` — that registry is scoped to the simpler no-arg
`fetch() -> list[dict]` trend-source adapters in
`backend.jobs.research_trend_v1` (google_trends, reddit, amazon_bestsellers,
etc.). CJ public evidence does not register there either, and DataForSEO
search evidence is not a trend source.

Every parse/normalize/evidence decision is delegated to
`evaluation.commerce.dataforseo_adapter.build_dataforseo_adapter_report()`
— this file adds no parsing logic of its own.

## Offline behavior (this release)

`fetch_search_evidence(query, *, context, request_kind=...)`:

1. If `context.dry_run` is `True` (the default on `SidecarContext`), calls
   the existing offline builder with `live_read_only=False` and wraps its
   `DataForSEOAdapterReport` in a new, small `DataForSEOSearchEvidence`
   dataclass (source, request kind, query, status, readiness state,
   blockers, signal counts, confidence, warnings, and the full nested
   report as a plain dict).
2. If `context.dry_run` is `False` (a live request), the offline builder is
   **never called**. A structured `blocked_live_mode` result is returned
   instead, naming every unmet prerequisite explicitly (see "Future
   activation prerequisites" below). This is not an exception and not a
   silent no-op — every blocker is enumerated in `evidence.blockers`.

`discover_search_queries(query, *, context, max_results=5)` returns the
whitespace-normalized input query only — no live keyword-suggestion call is
made in this release.

## Canonical `ProductResearchProvider` integration (this update)

Two additions make the adapter directly usable by anything that already
speaks `backend.contracts.adapters.ProductResearchProvider`'s
`async def discover(query, *, context) -> Sequence[Mapping[str, Any]]`
shape, without a second Protocol or registry:

- **`discover(query, *, context, request_kind=...)`** (module-level
  `async` function) — dry-run: returns every normalized search/shopping/
  competitor signal already produced by `fetch_search_evidence`, as plain
  mappings, each enriched with `request_kind` and `readiness_state` so a
  caller sees query lineage, source method, confidence, and limitations
  without re-deriving them from the nested report. Live
  (`context.dry_run=False`): returns a single-element sequence containing
  the structured `blocked_live_mode` result — the network is never called.
- **`DataForSEOResearchAdapter`** — a stateless class wrapper (`health()` +
  `async def discover(...)`) around the same module functions, for callers
  that prefer an instance over free functions. Holds no registry entry and
  no state of its own; a fresh instance is always behaviorally identical to
  calling the free functions directly.
- **`signals_to_additional_evidence(signals)`** — the per-signal
  counterpart to `to_additional_evidence`: shapes a `discover()` result into
  `{"dataforseo_signals": [...]}` for `ResearchCandidate.additional_evidence`.
  The two helpers use distinct keys (`"dataforseo"` vs. `"dataforseo_signals"`)
  and can coexist on the same candidate without collision.

Both `discover()` and `DataForSEOResearchAdapter.discover()` are `async`
only for Protocol conformance — no I/O occurs; everything is delegated to
the same offline, instantaneous builder. Default Commerce MVP behavior is
unchanged when this adapter is not supplied: `build_research_candidates(...)`
called with no `additional_evidence_by_id` still produces candidates with
`additional_evidence == {}`, exactly as before this adapter existed
(verified by `test_build_research_candidates_default_behavior_unchanged_without_dataforseo`
in `tests/test_dataforseo_product_research_integration.py`).

## Evidence mapping

`to_additional_evidence(evidence)` shapes a `DataForSEOSearchEvidence` into
`{"dataforseo": evidence.to_dict()}`, the exact shape
`backend.mvp_commerce.product_research.ResearchCandidate
.additional_evidence` already expects — the dataclass's own docstring calls
this bag "a deliberately generic bag... so a future source can be attached
without changing this dataclass's shape." Nothing in this PR constructs a
`ResearchCandidate` directly; the caller decides which `candidate_id` a
result attaches to.

## Failure states

| `evidence.status` | Meaning |
|---|---|
| `dry_run_ready` | Offline fixture parsed; readiness gates (approval/terms/privacy) still unmet, as expected pre-activation |
| `blocked_live_mode` | A live request was requested; refused outright, every prerequisite named |

`evidence.blockers` always includes `approval_missing`, `terms_review_missing`,
`privacy_review_missing` in dry-run mode (reflecting the real, unmet state
of the Approval Ledger / terms-privacy review today), plus `credential_missing`
if the `credential-dataforseo` reference is ever absent from the Credential
Registry.

## Timeout / retry policy

None exists in this release because no transport exists. A future,
separately reviewed transport PR must define: a bounded timeout (proposed:
10s, matching `scripts/run_phase1_live_validation.py`'s existing
`_diagnose_reachability` convention), a single bounded retry on 5xx only,
and fail-closed (no retry) on 4xx/auth/quota errors.

## Cost / approval policy

Unchanged from the offline layer: `evaluation/companyos
/resource_execution_governor.py`'s `ProviderSpendPolicy` currently
**hard-blocks** DataForSEO spend outright, and the Approval Ledger
`provider_call` request type governs any future activation. This PR does
not request, approve, or relax either.

## Future activation prerequisites

Before any live transport may be implemented:

1. An approved Approval Ledger request (`approval_request_type=provider_call`).
2. A configured credential reference (`credential-dataforseo`) with the
   secret value held only in a platform secret manager — never in this
   repository.
3. An approved monthly/per-run budget cap.
4. Complete terms review.
5. Complete privacy review.
6. Passing output-contract tests against real (not fixture) responses.
7. A defined timeout/retry policy for the real transport.
8. Workspace and client-isolation checks passed for the credential scope.
9. A separately reviewed live transport implementation (this PR contains none).

## Rollback / disable

Nothing to roll back — this release performs no live action. To disable:
do not call `fetch_search_evidence`/`discover_search_queries`, or leave the
`credential-dataforseo` reference absent (the underlying offline builder
already reports `credential_missing` in that case). No schema migration, no
event-type deprecation, no data to unwind.

## Safety boundaries

No credentials, API keys, OAuth tokens, provider calls, model calls, SDKs,
network calls, raw HTML, raw provider payloads, or external mutations occur
in this release. `evidence.report["safety_summary"]` (delegated straight
from the offline module) asserts `read_only=True`, `network_calls=False`,
`sdk_used=False`, `raw_payload_stored=False`, `raw_html_stored=False`,
`credentials_loaded=False`, `fail_closed=True` on every call.
