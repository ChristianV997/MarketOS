# CompanyOS Approval Ledger v1

The Approval Ledger is the canonical offline gate for future CompanyOS integrations. It turns the risk vocabulary already defined by the agent, skill, tool, workflow, model, evaluation, and knowledge registries into explicit requests, conditions, simulations, decisions, and audit records.

It is not an approval provider or an execution engine. The current implementation always keeps `read_only=true`, `network_calls=false`, `mutated=false`, and `external_action_performed=false`. A simulated approval is never live authority.

## Why the ledger comes before integrations

The registry layer describes what an agent, skill, tool, workflow, or model route could do. The ledger answers whether a specific action would need approval, which human role would review it, what evidence is missing, which budget cap applies, and how the decision would be recorded. This makes later integrations easier to test and safer to audit.

The ledger does not install or call CRM, email, WhatsApp, SMS, voice, payments, accounting, advertising, Shopify, supplier, model, vector, hosting, or domain systems.

## Request lifecycle

Requests use explicit statuses: `draft`, `pending_review`, `approved`, `denied`, `expired`, `revoked`, `simulated`, and `blocked_by_policy`.

The normal future lifecycle is `draft` -> `pending_review` -> a human decision. Requests can expire or be revoked. In this version the transition helper refuses to grant a live `approved` state. Revocation creates a revocation record and audit event.

Every request includes an action scope, offline environment, expiry requirement, risk level, conditions, budget cap, time window, registry links, sanitized evidence references, and immutable safety flags.

## Policy classes

- `approval_required`: a future human review is required;
- `approval_possible_later`: conditions and caps are eligible for a future approval implementation;
- `blocked_in_current_mode`: the action is unavailable in this offline release;
- `approved_simulation_only`: a local draft is safe to produce but is not execution authority.

Manual imports and draft artifacts are safe read-only examples. Provider calls, vector indexing, CRM writes, accounting sync, messages, payments, orders, ads, publishing, domain changes, and hosting changes are blocked in the current mode.

## Outreach consent gates

Email, WhatsApp, SMS, voice, and customer-message requests require explicit consent, a false do-not-contact flag, an approved message, and any relevant unsubscribe or AI-disclosure language. The CLI only simulates these conditions. It never sends a message or stores a real recipient.

## Model spend gates

Local and cheap routes are represented with per-run and monthly caps. An under-cap `model_spend` simulation can return `would_auto_allow_draft`; this only means that a future bounded run could be considered. Unknown routes, over-cap requests, frontier routes, and live model calls remain review-gated or blocked. No model call occurs.

## Provider, data, and content gates

Manual sanitized evidence can be assessed offline. Public/provider acquisition needs a later network gate plus source, robots/TOS, privacy, and budget review. Scraping/proxy behavior is not enabled. Site payloads, launch assets, and reports remain drafts. Publish, ad launch, supplier order, and payment requests are blocked even if a human approver placeholder is present.

## Audit trail and evidence

Each request receives a creation event. Status changes, decisions, and revocations use a stable approval ID, actor placeholder, timestamp, before/after status, reason, and evidence references. Tokens, passwords, authorization headers, private recipients, bank data, and raw provider payloads are rejected or never accepted by the CLI.

## Commands

```powershell
python scripts/run_companyos_approval_ledger.py --json
python scripts/run_companyos_approval_ledger.py --markdown
python scripts/run_companyos_approval_ledger.py --simulate-action send_email --markdown
python scripts/run_companyos_approval_ledger.py --simulate-action publish_site --markdown
python scripts/run_companyos_approval_ledger.py --simulate-action model_spend --requested-budget 0.20 --json
python scripts/run_companyos_approval_ledger.py --approval-requests tests/fixtures/companyos_approval/approval_requests_seed.json --json
python scripts/run_companyos_approval_ledger.py --output artifacts/companyos_approval/latest --markdown
```

With `--output`, only sanitized ledger, queue, policy, audit, simulation, blocked-action, and budget-cap files are written. Generated artifacts are local outputs and must not be committed.

## Roadmap and safety boundary

The ledger is the prerequisite for a future credential registry, bounded LiteLLM gateway, Langfuse/Phoenix trace sink, and Sales Department v2. Those integrations require a new review of secrets, ownership, budgets, privacy, provider terms, and live-action tests.

No credentials, API keys, model credentials, private recipients, client data, raw payloads, live network calls, provider calls, model calls, vector indexing, CRM mutations, accounting sync, email, WhatsApp/SMS, voice calls, payments, ads, publishing, orders, or customer messages are performed by Approval Ledger v1.
