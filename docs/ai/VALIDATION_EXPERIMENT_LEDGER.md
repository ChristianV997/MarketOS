# Validation Experiment Ledger

The validation experiment ledger is an offline-first typed record for deciding what a simulated validation experiment means. It is additive: it does not replace the opportunity synthesis scorer, economics kernel, resource execution governor, CompanyOS Approval Ledger, or TrustOS workspace boundary.

## Contract

`build_validation_experiment_ledger(payload)` accepts a sanitized mapping containing:

- hypothesis, candidate, target segment, permitted offline channel, test method, evidence required, and measurement method;
- assumed budget, sample target, success/kill/iterate thresholds;
- price, product cost, and CAC values represented through the canonical Decimal economics kernel;
- approval state, simulated result status, provenance, and workspace identity.
- optional normalized candidate/evidence mappings from discovery and research,
  with product/service/hybrid/unknown offering kind and geographic uncertainty.

The result preserves:

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
10. classify simulated results and choose a deterministic offline decision;
11. fingerprint canonical output.

The pipeline emits deterministic JSON through `to_json()` and a bounded
client-safe Markdown summary through `to_markdown()`. Missing opportunity
inputs remain missing; candidate identity alone never creates synthetic demand
or supply scores. Explicit zero money remains distinct from missing money.

## Decision semantics

- Strong demand without `reachable_buyer`: `hold_unreachable_buyer`.
- Negative base contribution after CAC: `kill_negative_unit_economics`.
- Missing experiment budget: `blocked_missing_budget`.
- Invalid simulated result: `reject_invalid_result`.
- Failed result: `kill_failed_result`.
- Successful result: `advance_to_human_review`, never launch authorization.
- Inconclusive or simulated result: `iterate_inconclusive_result`.

These are planning classifications, not permissions to spend, publish, advertise, contact customers, order inventory, pay suppliers, call providers, or write databases.

## Safety boundaries

The ledger is deterministic, fixture/manual-input only, read-only, and network-free. It never sends messages, calls providers, launches ads, publishes, places orders, makes payments, reserves inventory, contacts customers, or writes a database. Approval state is recorded as draft, pending review, or blocked-by-policy; it cannot grant external authority. Workspace identity must match and unsafe/sensitive keys fail closed.

## Tests and fixtures

Focused tests cover strong demand with no reachable buyer, negative unit economics, missing supplier evidence, missing budget, fixture-versus-live semantics, explicit zero versus missing costs, stale/future/conflicting evidence, successful/failed/inconclusive/invalid/simulated results, workspace mismatch, unsafe payloads, deterministic fingerprints, and safe no-mutation output.
