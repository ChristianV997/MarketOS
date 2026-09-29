# Validation Experiment Ledger

The validation experiment ledger is an offline-first typed record for deciding what a simulated validation experiment means. It is additive: it does not replace the opportunity synthesis scorer, economics kernel, resource execution governor, CompanyOS Approval Ledger, or TrustOS workspace boundary.

## Contract

`build_validation_experiment_ledger(payload)` accepts a sanitized mapping containing:

- hypothesis, candidate, target segment, permitted offline channel, test method, evidence required, and measurement method;
- assumed budget, sample target, success/kill/iterate thresholds;
- price, product cost, and CAC values represented through the canonical Decimal economics kernel;
- approval state, simulated result status, provenance, and workspace identity.
- optional normalized candidate/evidence mappings from discovery and research,
  with product/service/hybrid/unknown offering kind and geographic uncertainty;
  the public `normalize_opportunity_inputs` adapter accepts sanitized
  `normalized_candidate`/`candidate_report` and
  `geographic_context`/`geographic_research` aliases without importing their
  implementations.

The result preserves:

- the experiment hypothesis, target offering, candidate identity, expected decision,
  and explicit success/failure/iterate criteria;
- a typed evidence register with source, source class, evidence mode/state, and
  candidate identity for the market, demand, supplier, logistics, and marketing
  pillars; economics coverage is reported from the canonical money inputs;
- separate pillar coverage: demand or attention evidence never becomes supplier
  proof, and supplier proof must be explicitly marked on supplier evidence;
- deterministic evidence mode and state, including fixture/manual/unknown, stale, future, conflicting, and missing evidence;
- explicit zero costs separately from missing costs;
- base, downside, and upside economics from `backend.economics.kernel.calculate_scenarios`;
- the canonical opportunity-synthesis authority reference;
- simulated Approval Ledger, resource governor, TrustOS, and workspace-isolation decisions;
- a thin `MarketOS.ValidationOpportunityPipeline.v1` projection containing the
  hypothesis, cheapest offline falsification test, thresholds, result
  classification, next action, evidence provenance/freshness/conflicts, and
  geography/trade uncertainty;
- blockers, evidence gaps, assumptions, limitations, client-safe metadata, and a SHA-256 fingerprint.

## Call graph

`build_validation_experiment_ledger`

1. validate workspace, thresholds, offline channel, provenance, and typed money;
2. reject sensitive nested payloads and external-action claims;
3. normalize evidence states and freshness/conflict limitations;
4. call `backend.economics.kernel.calculate_scenarios`;
5. consume normalized candidate mappings without importing discovery/research
   implementations, then call the `evaluation.commerce.opportunity_synthesis`
   scoring authority;
6. call CompanyOS `simulate_action` for the Approval Ledger;
7. call `evaluate_execution_request` for resource/budget/runaway governance;
8. record a TrustOS hard block for ad execution;
9. create a client-safe workspace summary;
10. project target offering, decision criteria, six-pillar evidence coverage, and
    mandatory human-review metadata;
11. classify simulated results and choose a deterministic offline decision;
12. fingerprint canonical output.

The pipeline emits deterministic JSON through `to_json()` and a bounded
client-safe Markdown summary through `to_markdown()`. Missing opportunity
inputs remain missing; candidate identity alone never creates synthetic demand
or supply scores. Explicit zero money remains distinct from missing money.

## Decision semantics

- Strong demand without `reachable_buyer`: `hold_unreachable_buyer`.
- Negative base contribution after CAC: `kill_negative_unit_economics`.
- Missing experiment budget: `blocked_missing_budget`.
- Missing price, product cost, or CAC: `blocked_missing_economics`; missing is never treated as zero. A missing price or product cost is never passed to `calculate_scenarios` as a fabricated `Money.zero(...)` — `economics["status"]` stays `"unavailable"` and `economics["scenarios"]` stays empty rather than reporting computed-looking numbers built on an absent input. A missing CAC alone still lets scenarios compute (`economics["status"] == "computed"`), since the kernel already represents "no CAC assumed" as `None`, not zero; the decision is still blocked pending the missing value.
- Missing required supplier evidence: `blocked_supplier_evidence`; supplier identity or availability is never inferred.
- Manual or unavailable result: retained as distinct classifications and never promoted as successful evidence.
- Invalid simulated result: `reject_invalid_result`;
- Failed result: `kill_failed_result`;
- Successful result: `advance_to_human_review`, never launch authorization.
- Inconclusive or simulated result: `iterate_inconclusive_result`.
- Empty result lists and external-action labels fail closed; a missing result is
  represented as the default `simulated` classification only when no result list
  was supplied.

These are planning classifications, not permissions to spend, publish, advertise, contact customers, order inventory, pay suppliers, call providers, or write databases.

## Safety boundaries

The ledger is deterministic, fixture/manual-input only, read-only, and network-free. It never sends messages, calls providers, launches ads, publishes, places orders, makes payments, reserves inventory, contacts customers, or writes a database. Approval state is recorded as draft, pending review, or blocked-by-policy; it cannot grant external authority. Workspace identity must match and unsafe/sensitive keys fail closed.

`target_offering`, `expected_decision`, `decision_criteria`, `evidence_register`,
`pillar_evidence`, and `human_review` are projections for review and planning.
They do not add a ranker, economics kernel, TrustOS boundary, readiness gate, or
provider client. The deterministic fingerprint covers these projections and the
existing canonical-authority outputs.

## Tests and fixtures

Focused tests cover strong demand with no reachable buyer, negative unit economics, missing supplier evidence, missing budget, fixture-versus-live semantics, explicit zero versus missing costs, stale/future/conflicting evidence, successful/failed/inconclusive/invalid/simulated results, workspace mismatch, unsafe payloads, deterministic fingerprints, and safe no-mutation output.
