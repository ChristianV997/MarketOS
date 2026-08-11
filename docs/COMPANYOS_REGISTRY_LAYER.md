# CompanyOS Agent / Skill / Tool / Workflow Registry v1

The registry is the control plane before live agents. It defines what an agent may do, which skills are verified, which tools are risky, how workflows pause and resume, which model tier a task may use, what traces/evals are required, and which knowledge sources can later be retrieved.

It is intentionally offline. It does not install external systems, call providers, route model requests, index documents, send messages, publish sites, spend money, create payments/orders, or mutate CRM/accounting systems.

## Run it

```powershell
python scripts/run_companyos_registry_layer.py --json
python scripts/run_companyos_registry_layer.py --markdown
python scripts/run_companyos_registry_layer.py --include-architecture --include-agents --include-skills --include-tools --include-workflows --include-model-router --include-evals --include-knowledge --markdown
python scripts/run_companyos_registry_layer.py --output artifacts/companyos_registry/latest --markdown
```

## Registry layers

- Architecture registry: curated references, license/security/cost risk, emulation mapping, and integration decisions.
- Agent registry: managers and specialists with departments, budgets, run modes, handoffs, forbidden actions, trace, and eval requirements.
- Skill registry: in-repo procedures with input/output contracts, acceptance tests, boundary tests, and verification status.
- Tool registry: schemas, provider candidates, auth modes, risk levels, cost estimates, sandbox policy, audit events, and approval policy.
- Workflow registry: triggers, steps, checkpoints, retries, failures, interruptions, and output contracts.
- Model router: tiers, provider candidates, per-run/monthly caps, fallback policy, and blocked live-action routes.
- Trace/eval registry: redaction policy, prompt versions, datasets, metrics, regressions, and quality gates.
- Knowledge registry: source types, access/freshness/citation policies, memory scopes, and future vector-index boundaries.

## External architecture references

Onyx and Dify inform company-brain and app/workflow contracts. LangGraph, Inngest, Trigger.dev, Temporal, and Windmill inform checkpoints, retries, and interrupts. LiteLLM informs model routing and spend caps. Langfuse and Phoenix inform trace/eval policy. Hermes Skills Hub, ECC, and agency-agents inform curated procedures, roles, and boundary tests. MCP, Composio, Pipedream, Activepieces, and n8n inform tool catalogs. OpenHands and Herdr inform session envelopes and sandboxing. LlamaIndex, Haystack, Supabase pgvector, vLLM, Ollama, llama.cpp, and AWS Bedrock/AgentCore remain future architecture candidates.

The registry currently emulates contracts. LiteLLM and Langfuse are the highest-priority future integration candidates, but only after a concrete workload, owner, budget, security review, and approval-ledger gate exist. Onyx and LangGraph are useful emulation references now. License terms and current security posture must be reviewed before adoption.

## Safety policy

All real-world tools default to `blocked` or approval-required. Sales skills draft messages but cannot send them. Finance skills plan budgets but cannot spend. Accounting skills produce ledger seeds but cannot post them. Workflows pause before external action, spend, message send, publish, payment, and order. Model routes stop when a budget or safety gate fails. Knowledge sources are not indexed and private/secret fields are excluded.

The next architecture milestone is Approval Ledger v1, followed by bounded Sales v2 and only then carefully scoped external adapters.

Approval Ledger v1 is now the canonical action gate over this registry. It reuses tool risk, workflow interrupts, agent boundaries, skill approval requirements, model caps, evaluation gates, and knowledge privacy policies without installing any of the referenced systems.
