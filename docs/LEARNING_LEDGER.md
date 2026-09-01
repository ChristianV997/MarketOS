# Learning Ledger v1

The Learning Ledger is MarketOS's deterministic memory of decisions and outcomes. It records what was tried, the evidence used, the result, why it worked or failed, and the bounded next action. It is the learning layer beneath the Resource & Execution Governor; it is not a database, vector store, analytics collector, or autonomous optimizer.

## Why it exists

A company improves when wins are repeatable, losses are not repeated, and inconclusive tests are treated as requests for better evidence. Learning events turn product validation, supplier proof, creative tests, landing-page tests, provider dry runs, model routing, TrustOS reviews, and portfolio decisions into structured lessons.

The default ledger is synthetic and offline. It uses placeholders and sanitized fixtures, never real client data, live metrics, prompts, credentials, provider payloads, or external calls.

## Core records

Every `LearningEvent` links a source decision, department, workspace scope, evidence references, action, cost assumption, metrics, outcome, confidence, reasons, winner/loser attributes, do-not-repeat rules, and iteration recommendations. `LearningExperiment` adds the hypothesis, metric, kill/scale thresholds, and learning requirement needed before another iteration.

Outcomes are `win`, `loss`, `inconclusive`, `killed`, `scaled`, `paused`, `iterated`, `blocked`, `needs_more_evidence`, and `invalid_test`. Failure and success taxonomies are deliberately bounded so aggregation remains deterministic and reviewable.

## Rules and recommendations

Losses and blocked actions can produce `LearningDoNotRepeatRule` records such as: require a hypothesis and kill rule before an ad experiment; do not use frontier reasoning for low-evidence work; do not retry a provider after its cap without new evidence; and do not create a new site when an existing brand can absorb the test. Rules carry severity, block behavior, review period, source event, and client visibility.

`LearningIterationRecommendation` records the smallest next change: improve a creative angle, fix an offer or page, obtain supplier proof, complete terms/privacy evidence, use a cheaper model tier, or capture missing learning before continuing.

## Governor feedback

`LearningDecisionInfluence` is the handoff contract for the Resource & Execution Governor. Prior wins can support a controlled scale decision; prior losses reduce priority or create a kill/soft-block; missing learning blocks another iteration; recurring TrustOS or provider blockers require evidence completion. The ledger does not mutate Governor behavior or authorize execution.

Portfolio impacts summarize working and failing categories, hooks, offers, price points, landing-page patterns, supplier types, provider usefulness, and recurring TrustOS blockers. Model-routing impacts record when algorithmic, local, cheap, frontier, or human review was sufficient. Provider impacts distinguish useful dry runs from terms, privacy, schema, budget, or approval blockers.

## Client-safe visibility

The ledger preserves `internal_only`, `workspace_only`, `client_visible_summary`, `aggregated_safe_summary`, and `blocked` visibility. Client-safe summaries contain status, bounded lessons, blockers, evidence requirements, and next actions only. They never expose prompts, formulas, heuristics, source code, global provider intelligence, cross-client learning, credentials, or raw metrics.

**Known vocabulary drift (recorded during the recovery pass, not silently changed):** this `VISIBILITY` tuple is parallel to, but not byte-identical with, `evaluation/trustos/client_workspace_isolation.py`'s `ACCESS_MODES`. `internal_only`, `workspace_only`, and `blocked` match exactly; `client_visible_summary` here corresponds to `client_visible` there; `aggregated_safe_summary` here corresponds to `aggregated_safe_summary_only` there; and `redacted_summary_only` has no counterpart here. The ledger still enforces its own visibility gating and rejects client-private and secret-like input, so this is a consistency gap rather than a leak path. It was left un-renamed because renaming would change the recovered schema and the semantics its tests encode — reconciling the two vocabularies belongs to a follow-up lane that owns both modules.

## Commands

```text
python scripts/run_learning_ledger.py --json
python scripts/run_learning_ledger.py --markdown
python scripts/run_learning_ledger.py --event-type ad_experiment --markdown
python scripts/run_learning_ledger.py --scenario ads_winner_loser --markdown
python scripts/run_learning_ledger.py --scenario frontier_llm_waste --markdown
python scripts/run_learning_ledger.py --output artifacts/learning_ledger/latest --markdown
```

Output is not written unless `--output` is supplied. The CLI rejects secret-like and client-private fixture markers. No database, vector memory, model call, provider call, ad, publishing, payment, order, message, or authentication action exists in v1.

## Future path

Later work may persist approved learning events behind Client Workspace Isolation and a reviewed database/RLS design. That future system must retain provenance, professional-review boundaries, and deletion/retention policy. It must not turn the ledger into autonomous spend, publishing, outreach, or customer-action authority.
