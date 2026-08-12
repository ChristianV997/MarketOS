# Resource & Execution Governor

The Resource & Execution Governor is the company-level decision layer for CompanyOS. Departments propose work; the governor checks evidence, budgets, quotas, portfolio fit, experiment design, runaway limits, TrustOS gates, workspace boundaries, and Approval Ledger state before returning a deterministic simulated outcome.

## What it governs

The governor covers product screening and validation, launch/site drafts, brands, inventory exposure, creative and ad experiments, sales drafts, provider pulls, security/TrustOps/CompanyOS reviews, client exports, model tiers, and agent workflows. Outcomes include `allow`, `warn`, `queue`, `soft_block`, `hard_block`, review requirements, `kill`, `scale`, and `pause`.

Algorithmic scoring is preferred for deterministic work. Local models handle bounded internal tasks, cheap models handle routine drafting, frontier reasoning requires evidence, budget, and management review, and human review is required for legal, tax, security, and external-action decisions. Live execution remains blocked.

## Budgets, quotas, and portfolio

Budgets track limits, usage, reservations, soft caps, hard caps, and approval thresholds for models, providers, ads, inventory, websites, brands, creative, reports, and client exports. Quotas cap cycles, reports, workflows, and capacity. The portfolio rule is: many ideas enter, few become candidates, fewer become experiments, and only winners scale.

New brands and websites are blocked when an existing brand/category can absorb the opportunity. Inventory requires supplier proof and finance capacity. Provider work requires a registered provider, terms/privacy review, output contract, budget, credential reference, and Approval Ledger authorization for future live calls.

## Experiments and runaway protection

Ad/content experiments require a hypothesis, budget cap, sample target, success metric, kill threshold, scale threshold, and learning capture. Winners scale in controlled increments; losers are killed after sufficient evidence; inconclusive tests pause. Workflow steps, retries, child tasks, spawned agents, provider calls, model calls, frontier calls, output files, runtime, budget, and repeated outputs are capped.

## Cross-department wiring

Promotion combines Intelligence, Supplier, Consumer Attention, Finance, TrustOS, Approval Ledger, and Management. New sites combine Launch, Website/Store/Funnel, Finance, TrustOS, Workspace Isolation, and Management. Provider pulls combine Provider Registry, Finance, TrustOS, and Approval Ledger. Model usage combines Model Router, Finance, Runaway Guard, and TrustOS. This is coordination metadata, not a project-management clone or Learning Ledger.

## Commands and safety

```text
python scripts/run_resource_execution_governor.py --json
python scripts/run_resource_execution_governor.py --action create_new_website --markdown
python scripts/run_resource_execution_governor.py --scenario product_to_launch_pipeline --markdown
python scripts/run_resource_execution_governor.py --scenario ads_kill_scale_loop --markdown
python scripts/run_resource_execution_governor.py --scenario model_cost_control --markdown
python scripts/run_resource_execution_governor.py --output artifacts/resource_execution_governor/latest --markdown
```

The module performs no model/provider calls, ad launches, publishing, orders, payments, messaging, auth, database writes, tenant creation, or client-data processing. Output writing requires explicit `--output` and writes only sanitized deterministic reports.
