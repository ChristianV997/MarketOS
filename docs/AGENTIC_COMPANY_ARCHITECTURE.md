# MarketOS Agentic Company Layer

MarketOS “DAO” means governed delegation and auditable company operations, not
blockchain, tokens, wallets, crypto voting, or on-chain execution.

## Mapping

| Company concept | MarketOS primitive |
|---|---|
| Business cell | Workspace identifier |
| Execution evidence | Existing runtime/artifact records |
| Pre-execution intent | `backend.governance.proposal.Proposal` |
| Approval record | `GovernanceDecision` and `ApprovalPolicy` |
| Agent team | `Department` |
| Planner | Manager role |
| Executor | Specialist role |
| Quality/risk control | Reviewer role |
| Human-readable memory | Optional local Obsidian vault |
| Machine-readable audit | JSON registries and existing runtime state |

The current loop is: planner → approval policy → dry-run executor → reviewer
decision record → Obsidian note → next cycle. It never performs live ads,
orders, customer messages, supplier actions, payments, or production changes.

Implemented now:

- typed agent roles and departments with safe JSON persistence;
- proposal and decision lifecycle records;
- deterministic dry-run approval evaluation;
- a small planner/executor/reviewer compatibility loop;
- a fail-closed service contract registry with verified read-only fallbacks for
  unit economics and creative-script generation;
- route modules for organization inspection and governance runs;
- path-safe filesystem Obsidian rendering, skipped when no vault is configured.

The current safe service map is intentionally narrow. Unit economics wraps the
existing deterministic `evaluation.calculate_unit_economics`; creative growth
wraps the existing text generator in dry-run mode. Product research, customer
intelligence, and profit-stack advisory remain unavailable because this
checkout has no verified read-only service boundary for them. The loop reports
an unavailable service rather than inventing business logic.

Future work: authentication, billing, real human accounts, external approval
workflows, Slack/Telegram approvals, Obsidian REST/MCP, durable multi-process
registries, richer experiment linkage, and any legally justified blockchain
research. None is enabled by this layer.
