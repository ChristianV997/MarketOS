# Business Opportunity Evaluation Playbook

Status: offline consulting methodology, fixture-backed and advisory.

This playbook gives an operator a repeatable way to examine a business idea
without turning a thin evidence set into a market claim. It is intentionally
product-agnostic. It applies to ecommerce goods, importation, digital
products, digital services, physical services, geographic arbitrage, a
client-proposed idea, and an opportunity discovered in evidence.

It is a method and a review checklist, not a runtime authority. It does not
score, rank, calculate unit economics, authorize promotion, bill a client,
manage a CRM, or authorize a launch. A future executable implementation must
compose the authorities named below rather than fork them.

## Authority and Boundary

Use the existing MarketOS authorities:

- `backend/economics/kernel.py` is the canonical Decimal `Money`, `EvidenceRef`,
  `MarketLane`, assumptions, and service-economics contract. Adapters may
  render its results but must not reimplement its arithmetic.
- `evaluation.commerce.opportunity_synthesis` is the existing opportunity
  fusion and ranking authority when a ranked product report is required. This
  playbook supplies review questions; it does not create another ranker.
- `scripts/research_to_decision.py` and the existing evidence adapters preserve
  source identity, freshness, conflict findings, missing fields, and evidence
  ceilings. Use their packet and references rather than copying raw source
  material into a client report.
- `evaluation.trustos.client_workspace_isolation.py` is the internal-to-client
  boundary. Client output must be a sanitized projection tied to the registered
  workspace; it must not contain internal prompts, formulas, heuristics, source
  code, cross-client data, credentials, raw provider payloads, or filesystem
  paths.
- CompanyOS Approval Ledger and Resource Execution Governor remain separate
  control authorities. A playbook recommendation cannot approve spend,
  publishing, outreach, orders, payments, or a provider call.

The playbook is not a scorer, not a ranker, not an economics engine, not a
promotion gate, not a billing system, not a CRM, and not a launch authority.
It cannot upgrade fixture, manual, derived, simulated, or planned evidence to
live proof. It cannot authenticate a supplier, establish legal clearance, or
prove commercial demand.

## Opportunity Record

Keep one bounded record per opportunity. The record may be rendered as JSON or
Markdown, but the following fields retain the identity and limits of the
review:

| Field | Meaning and safety rule |
| --- | --- |
| `opportunity_id` | Stable review identity, not a product claim. |
| `candidate_id` | Candidate identity from the source authority. Never infer it from a scenario template or filename. |
| `workspace_id` | Registered workspace identity. Reject a missing, unknown, or mismatched workspace. |
| `offering_kind` | `goods`, `service`, `hybrid`, or `unknown`; unknown is not silently treated as goods. |
| `client_objective` | Bounded client question, not a launch instruction. |
| `geography` and `language` | Intended market and communication context; neither proves reachability or legal access. |
| `claims` | Claim register using the taxonomy below. |
| `evidence` | References, class, source identity, capture/freshness, and conflict status. Never raw pages, HTML, logs, or provider payloads. |
| `assumptions` | Explicit planning inputs, including any scenario/template policy effect. |
| `unknowns` | Missing, stale, conflicting, unavailable, or unverified facts. |
| `blockers` | Fatal gates and the evidence needed to clear them. |
| `experiment` | Cheapest decision-changing test, with a bounded outcome and stop rule. |
| `fingerprint` | Stable hash of sanitized, sorted-key content; not an authenticity attestation. |

The candidate identity, workspace identity, source identity, and template
identity are separate fields. A template can define policy assumptions, but it
cannot contribute supplier, market, compliance, or customer evidence.

## Claim Taxonomy

Every sentence in a review should be classifiable:

- **Fact**: a supplied or observed value with source identity, capture context,
  and an admissible evidence class. Facts remain bounded by freshness and
  conflict findings.
- **Inference**: a deterministic interpretation of stated facts, such as
  "shipping is a decision-changing unknown." An inference is not a market
  observation or legal conclusion.
- **Hypothesis**: a testable proposition, such as "a reachable buyer may pay
  for this service through the stated channel." It needs an experiment.
- **Unknown**: missing, unavailable, stale, future-dated, conflicting, or
  unverified information. Unknown is never false, true, zero, approved, or
  cleared by default.

Use neutral wording: "reported by the supplied fixture," "planning
assumption," or "requires verification." Do not say "customers want," "the
supplier is approved," "the margin is positive," or "the market is legal"
unless the relevant authority and evidence actually support that claim.

## Evidence Classes and States

MarketOS uses evidence provenance and evidence state together:

| Class | Permitted interpretation |
| --- | --- |
| `fixture` | Synthetic test input only. Never live proof. |
| `manual` / `manual_import` | Operator-supplied material; provenance is retained but authenticity is not inferred. |
| `observed` | A bounded observation from an allowed source; it remains source- and time-specific. |
| `derived` | Deterministic output from other evidence; it does not add independent proof. |
| `simulated` | Offline behavior or scenario result; it is not a real transaction or market result. |
| `planned` | A proposed step, budget, threshold, or experiment; not an outcome. |
| `live` / `live_readonly` | Only an approved live-read-only contract may use this class; it is still not launch authorization. |

States such as `unknown`, `missing`, `stale`, `rejected`, `available`, and
`unavailable` describe usability at the current boundary. A class does not
override a blocking state. A manual claim of "verified" is still a claim until
the appropriate authority verifies it. `fixture`, `manual`, `derived`,
`simulated`, and `planned` evidence never becomes live proof through this
playbook.

## Review Modes

### Discover

Capture a candidate, the client question, offering kind, geography, language,
and the source references that caused the idea to be considered. Record what
is not known. Do not rank candidates or treat attention, search interest, or a
client idea as supplier proof.

### Evaluate

Examine reachable buyers, recurring pain, alternatives, supply gap, evidence
quality, economics inputs, regulatory risk, and platform risk. Separate facts,
inferences, hypotheses, and unknowns. An incomplete dimension remains
incomplete.

### Compare

Compare candidates only through the existing Product Opportunity Synthesis or
another explicitly named authority. This playbook can provide a common
checklist and explainability notes; it cannot produce a competing score,
ranking, or tie-breaker.

### Validate

Select the cheapest decision-changing experiment. Define the decision, the
minimum admissible observation, the evidence class, time/cost as a planning
assumption, a stop condition, and a safe result interpretation. Keep the
experiment dry-run or read-only unless a separate approved authority exists.

### Review-results

Compare the observed result to the predeclared hypothesis and stop rule. Mark
the result as fact, inference, hypothesis, or unknown. Preserve negative and
inconclusive results. A successful fixture or simulation validates only the
fixture or simulation path.

## Evaluation Dimensions

Eight evaluation lenses cover a review. Five are detailed below as
dimensions: `reachable_buyer`, `recurring_pain`, `current_alternatives`,
`supply_gap`, `evidence_quality`. The remaining three are covered
elsewhere in this document: `unit_economics` (see "Economics Worksheet,
Not an Engine"), `regulatory_risk` (see "Regulatory and Platform Risk"),
and `geography` (the market/language context recorded on every
Opportunity Record). `scripts/ai/validate_business_opportunity_playbook.py`
enforces this closed set of eight lens keys against every fixture's
`evidence[].dimension`.

### Reachable buyer

Identify the buyer, geography, language, channel, access constraint, and
ability to receive and pay for the offer. A foreign-market label is not a
reachable-buyer finding. If a channel, delivery path, or buyer access is not
shown, record `unknown` and block any demand or launch claim.

### Recurring pain

Describe the problem, recurrence, urgency, affected segment, and current
workaround. A single anecdote, attention signal, or client belief is a
hypothesis unless corroborated by admissible evidence.

### Current alternatives

Record how buyers solve the problem now, including manual workarounds,
substitutes, competitors, and switching friction. Do not call an alternative a
competitor without source evidence. Do not use a supply gap alone as demand.

### Supply gap

For goods, examine availability, fulfillment, quality, returns, and support.
For services, examine provider capacity, skills, response time, delivery
quality, and geographic coverage. A stated gap is not proof that a buyer can be
reached or that a supplier can deliver.

### Evidence quality

Check candidate/source/workspace identity, provenance, capture time, freshness,
future dates, conflicts, extraction method, evidence class, and missing fields.
Conflicting or stale evidence stays visible and is not silently averaged.

## Economics Worksheet, Not an Engine

Use the canonical economics kernel when an economic result is needed. This
playbook only names inputs and review questions:

- revenue or service price and currency;
- product/service cost and supplier quote;
- domestic or international shipping and delivery cost;
- duty, tax, brokerage, and customs assumptions;
- returns, refunds, defects, warranty, and support reserves;
- platform and payment fees;
- customer-acquisition cost (CAC) and any affiliate or channel fee;
- FX rate, timestamp, source, and uncertainty when currencies differ.

Use Decimal `Money` and preserve currency metadata. Currency mismatch must fail
closed until an explicit, provenance-backed FX conversion exists. A missing
cost, fee, return reserve, or FX input is unavailable, never an observed zero.
An explicit quoted zero is distinct from missing and remains marked with its
source and evidence class. Do not calculate a positive contribution from a
placeholder zero. Sensitivity analysis may vary a planning assumption, but it
must label the result as a scenario rather than evidence.

For every material input, state whether it is observed, derived, assumed, or
unknown. If the decision changes under a plausible logistics, duty, tax,
returns, platform-fee, CAC, or FX assumption, the experiment should target
that input instead of hiding the sensitivity in a composite number.

## Regulatory and Platform Risk

Check product/service restrictions, claims, privacy/data handling, tax and
customs context, professional licensing, platform terms, content rules,
returns, and language/jurisdiction constraints. `not_assessed`, `unknown`,
stale, or supplier-claimed compliance is a blocker, not clearance. This
playbook does not provide legal advice or regulatory certification.

## Cheapest Decision-Changing Experiment

Write an experiment record with:

1. **Decision**: the binary or bounded choice it can change.
2. **Hypothesis**: the claim to test, not a conclusion.
3. **Minimum observation**: the smallest evidence that would support or reject
   the hypothesis.
4. **Identity and provenance**: candidate, workspace, source, capture window,
   language, geography, and evidence class.
5. **Planning assumptions**: time, money, sample size, or threshold; never
   represent these as observed market facts.
6. **Stop rule**: what blocks, defers, or advances the next review.
7. **Safety boundary**: no credentials, provider activation, spend, order,
   message, publishing, or customer-data mutation in this methodology.

Choose the experiment that can change the decision, not the experiment that
produces the most attractive story. A null, blocked, or unavailable result is
valid evidence about the next action.

## Fatal Gates

Any of these gates blocks a positive recommendation until the stated issue is
resolved by the responsible authority:

| Gate | Required handling |
| --- | --- |
| No reachable buyer | Mark buyer access unknown and test channel/geography access. |
| Required evidence missing | Preserve the missing field and request the smallest evidence needed. |
| Workspace/source identity unresolved | Reject or quarantine the record; do not join it to another candidate. |
| Stale, future-dated, or conflicting evidence | Retain the conflict and require corroboration. |
| Missing economics treated as zero | Reject the calculation and repair the input contract. |
| Negative economics under explicit inputs | Do not present positive viability; investigate a changed assumption or reject. |
| Currency mismatch without explicit FX | Fail closed. |
| Regulatory or platform risk not assessed | Mark blocked/needs review; do not claim clearance. |
| Unsupported claim, secret, raw payload, or private path | Reject and sanitize before export. |
| No decision-changing experiment | Defer rather than invent certainty. |
| Unauthorized external action | Keep the output planned or simulated and route through Approval Ledger. |

## Archetype Coverage

| Archetype | First questions | Typical fatal gate |
| --- | --- | --- |
| Ecommerce goods | Can the buyer be reached and can the item be delivered with known landed cost? | Missing cost/logistics or unsupported demand. |
| Importation | Are origin, destination, duty, tax, brokerage, returns, and terms evidenced? | Lane or regulatory unknown. |
| Digital products | Is distribution reachable and is the value proposition supported? | No distribution evidence or fabricated demand. |
| Digital services | Who can buy, through which channel, and what delivery capacity exists? | Insufficient distribution/capacity. |
| Physical services | Can the provider serve the geography, schedule, and quality need? | Capacity, licensing, or buyer access unknown. |
| Geographic arbitrage | Does the price difference survive delivery, duty, tax, returns, fees, and FX? | Delta disappears or inputs are missing. |
| Client idea | What is supplied by the client versus independently evidenced? | Client belief relabeled as fact. |
| Evidence-discovered | What candidate identity and provenance led to discovery? | Correlated, stale, or non-identifying evidence. |

## Anti-patterns

- **Fake demand**: turn clicks, attention, search interest, or one anecdote
  into buyers, sales, conversion, or recurring demand.
- **Fake arbitrage**: show a source/destination price difference while omitting
  shipping, duty, tax, returns, platform fees, CAC, or FX uncertainty.
- **Fabricated social proof**: copy testimonials, reviews, follower counts, or
  engagement without source identity and capture context.
- **Unsupported compliance**: treat a supplier claim, template label, or blank
  status as legal, tax, privacy, platform, or professional clearance.
- **Identity collapse**: use a template candidate, filename, raw workspace
  string, or stale evidence to select another candidate or workspace.
- **Evidence inflation**: promote fixture, manual, derived, simulated, or
  planned output to live proof.
- **Zero substitution**: serialize a missing cost as numeric zero and then
  derive positive economics.
- **Authority duplication**: add a second scorer, ranker, economics engine,
  promotion gate, event spine, export layer, billing system, CRM, or launch
  authority.

## Client-Safe Boundary and Non-goals

Client output contains only the sanitized projection: opportunity identity,
workspace-bound provenance references, claim taxonomy, evidence class/state,
known assumptions, unknowns, blockers, bounded recommendation wording, and next
research action. It omits internal prompts, formulas, heuristics, source code,
raw HTML/provider payloads, credentials, private filesystem paths, cross-client
records, and professional packets not cleared for export.

This playbook does not provide authentication, tenant authorization, or
supplier verification. It does not provide legal advice, statistical market
sizing, payments, billing,
orders, advertising, publishing, messaging, CRM, provider integration,
customer-data persistence, or launch approval. It does not claim commercial
validation from fixtures or local execution.

## Operator Output Checklist

Before sharing a review, confirm:

1. Candidate and workspace identity are registered and consistent.
2. Every fact has admissible source identity, class, freshness, and conflict
   status; unknowns are explicit.
3. Missing and explicit zero inputs remain distinct, with currency metadata.
4. The applicable fatal gates, blockers, and next research actions are listed.
5. Template assumptions are labeled as assumptions and do not alter evidence
   identity.
6. The result is client-safe and has a deterministic fingerprint.
7. The output states `fixture`, `manual`, `simulated`, `planned`, or `live`
   honestly and does not imply live validation.
8. No external mutation was performed; any future action is Approval Ledger
   gated and human-reviewed.

The six tracked fixtures in `tests/fixtures/opportunity_playbook/` are
synthetic examples of these rules. They are contract inputs, not market facts
and not recommendations.
