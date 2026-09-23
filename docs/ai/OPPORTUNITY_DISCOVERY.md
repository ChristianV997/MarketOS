# Opportunity Discovery

`services.opportunity_discovery` is the offline, product-agnostic entrypoint for
screening supplied business opportunities. It accepts goods, services, hybrid
offers, and unknown offering kinds without generating unsupported market facts.
It is an adapter, not a second scoring, economics, Governor, or TrustOS
authority.

## Operator Command

Run a bounded JSON input with one of the five modes:

```powershell
python scripts/run_opportunity_discovery.py --mode discover --input .\candidate.json --format json
python scripts/run_opportunity_discovery.py --mode compare --input .\candidates.json --format markdown
```

The input is capped at 64 KiB, rejects duplicate JSON keys, rejects secret or
raw-payload-shaped fields, and bounds nested values and candidate count. The
command is read-only and does not register a workspace, call a provider, read
credentials, write a database, or authorize a commercial action.

## Modes

- `discover`: assess only candidates supplied in the input (or explicitly
  supplied under `evidence_candidates`). With no candidates, the result is
  `unavailable`; the engine never invents a market or product.
- `evaluate`: assess exactly one candidate.
- `compare`: assess two or more supplied candidates with stable candidate-ID
  ordering. It does not create a competing composite ranking score.
- `validate`: produce the cheapest bounded, decision-changing evidence
  experiment for one candidate. The experiment is a read-only plan.
- `review-results`: preserve supplied review results as operator input; local
  execution does not turn them into live commercial evidence.

## Authority Composition

```text
sanitized input
  -> opportunity_discovery contract and evidence gates
  -> backend.economics.kernel (Decimal Money, MarketLane, unit/service economics)
  -> evaluation.commerce.opportunity_synthesis (product-capable reports only)
  -> evaluation.companyos.resource_execution_governor (screening simulation)
  -> evaluation.trustos.client_workspace_isolation (injected registered export)
```

The adapter does not modify those authorities. Product synthesis remains the
canonical product three-pillar score. Economics remains the canonical Decimal
calculation. Governor output is the `screen_product_opportunities` simulated
decision, not launch permission. TrustOS export is attempted only when the
caller supplies an already registered workspace and registry; registration is
never performed by this module.

## Evidence Contract

Every evidence item has a semantic status and an independent source class.
Statuses are `observed_fact`, `derived_calculation`, `inference`, `hypothesis`,
`assumption`, `unknown`, and `unavailable`. Source classes are `fixture`,
`manual`, `observed`, `derived`, `simulated`, `unknown`, `unavailable`, and
`live_validated`.

`live_validated` claims are downgraded to `unavailable` because this offline
engine has no live-validation authority. A `supplier_claim` cannot become an
observed fact by naming its status as observed. Stale or conflicting evidence
stays visible and blocks or requires evidence. Local code execution is reported
separately as `actual_executed`; it never upgrades commercial evidence.

Missing money is not converted to zero. Explicit zero is accepted as an input
and remains serialized as zero. Missing price, product cost, required shipping,
or service scenario inputs create unavailable evidence and do not produce a
positive decision. Negative contribution is a fatal gate even when attention
or product-synthesis scores are high.

## Decision and Safety Semantics

Fatal gates are evaluated before a candidate can be `acceptable` or
`attractive`: restricted/legal category, unreachable buyer, unproven supply,
structurally negative economics, unacceptable compliance/operational risk, and
malformed or insufficient evidence. Otherwise the result is `needs_evidence`
until required evidence is complete. A `ready` result means ready for human
review only, never ready to launch.

Each candidate contains best/base/worst scenarios, evidence gaps, sensitivity
drivers, and an offline validation experiment with success, kill, and iterate
rules. Results include a stable SHA-256 fingerprint and deterministic Markdown.
No report authorizes ads, spending, publishing, outreach, orders, payments,
inventory, provider activation, or launch.

## Verification

```powershell
python -m pytest tests/services/test_opportunity_discovery -q
python -m compileall services/opportunity_discovery tests/services/test_opportunity_discovery
python -m ruff check services/opportunity_discovery tests/services/test_opportunity_discovery scripts/run_opportunity_discovery.py
```

The fixtures are synthetic and contain no raw provider payloads, secrets, or
client data. They exercise negative margin, missing supplier/freight evidence,
supplier claims, stale/conflicting observations, service/product/hybrid/unknown
offerings, malformed input, deterministic repeats, and TrustOS export.
