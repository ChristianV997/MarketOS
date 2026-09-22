# Service and Offering Market Research Boundary

`evaluation.companyos.service_market_research` is one bounded offline adapter for manual/fixture market evidence. It is not a service catalog, product-name scorer, launch gate, new event store, or client report authority. The JSON input contract is frozen as `MarketOS.ServiceMarketResearchInput.v1`; unknown and missing fields fail closed, duplicate JSON keys are rejected, and the input is capped at 64 KiB, 100 observations, and 200 evidence references.

The required top-level fields are `contract_id`, `candidate_id`, `offering_type`, `workspace_id`, `as_of`, `market_access`, `market_lane`, `observations`, and `economics`. Nested objects also have exact required-key sets; optional values must be explicit `null`, and all money, observation, lane, and evidence-reference objects reject unknown fields. Every evidence reference supplies source type, locator fields, captured/expiry times, state claim, confidence, and an optional digest-shaped snapshot hash.

The contract represents `service`, `goods`, `hybrid`, and `unknown` offerings without branching on product names. Services delegate Decimal arithmetic to `backend.economics.kernel.calculate_service_economics`. Goods are routed to the existing goods authority without this adapter scoring them. Hybrid and unknown offerings remain unassessed until classified. No second economics model is implemented.

Each amount and observation carries a canonical `EvidenceRef`. Effective evidence class comes from the trusted caller's source mode, not the imported `class`, `source_type`, or state-claim strings. The typed API defaults to `unknown`; the CLI classifies a local file as `manual`; fixture tests explicitly select `fixture`. `observed` is available only when the caller selects that source mode and the reference state is observed. Untrusted verified/live claims are reduced to a generic blocked marker and serialize with canonical state `unknown`; the literal privileged claim is not emitted. `not_assessed` and `not_applicable` remain distinct claims/statuses, not successful observations. No OCR, scraping, providers, credentials, or external research execute.

Service assessments project their available facts into the existing `evaluation.commerce.promotion.evaluate_promotion` gate with missing gates set to false. This is a readiness projection, not a second promotion authority: the service contract has no exact-SKU, supplier-permission, return, warranty, support-owner, compliance, or customer-promise proof, so fixture/manual results remain below launch stages and `promoted` remains false. Goods are routed to their existing goods authority; hybrid and unknown offerings remain unassessed rather than being promoted by this adapter.

Jurisdiction status is deliberately explicit but unresolved in this offline vertical. For `market_lane.destination_country` values `MX` (Mexico), `US` (United States), and `CA` (Canada), `market_access_assessment` remains `not_assessed`, the export remains `needs_evidence`, and the promotion `compliance` gate remains false. The lane label is routing context only; it is not tax, import, regulatory, or legal evidence. Any jurisdiction-specific conclusion must come from the existing compliance/TrustOS authorities with appropriate human or professional review; this adapter never certifies a country from fixture or manual observations.

Required service fee, labor, tooling, pass-through, and refund/revision reserve must be present with evidence before service contribution is calculated. An evidenced zero is distinct from an absent value. Missing capacity remains `not_assessed`; missing lane/jurisdiction evidence remains a blocker. Freshness and conflicting-observation checks apply to service, goods, hybrid, and unknown offerings before routing. Market access is always `not_assessed` by this offline path, even if a source claims otherwise. Fixture/manual/derived results do not authorize promotion, booking, orders, payments, publishing, or compliance clearance.

Run the reproducible local path with an existing workspace registry:

```powershell
python -m evaluation.companyos.service_market_research `
  --input tests/fixtures/service_market_research/service-mxn.json `
  --workspace-registry <existing-workspace-registry.json>
```

The command reads the input and registry only. It emits deterministic JSON to stdout and writes no report files. Deeply nested, oversized, duplicate-key, and malformed input fails with a bounded JSON error and no traceback. Output contains the canonical `Event`, `Event.replay_hash()`, replay certification summary, and the established TrustOS export. TrustOS revalidates the export payload immediately before serialization. Source URLs and document references are never serialized; approved-size locators are represented by a SHA-256 digest, and snapshot hashes must already be digest-shaped. Secret-shaped locators and arbitrary evidence-state claim strings are rejected.

`execution_class=actual_executed` means only that local adapter code ran. `decision_class=simulated_or_planned` and `live_validation=false` are independent. Evidence classes describe inputs; `derived` describes computed output. CI is not queried and remains outside this command's evidence.
