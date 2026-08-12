# Client Workspace Isolation Plan

Client Workspace Isolation is the offline boundary between the internal MarketOS core and a client-safe projection. A workspace is a policy-scoped view of approved status, blockers, evidence requirements, approvals, risks, and next actions. It is not a tenant, database, auth system, source-code fork, or copy of MarketOS internals.

## Boundary model

The plan uses four protections:

- Internal prompts, scoring formulas, heuristics, pricing and upsell notes, agent instructions, source code, cross-client learning, and global provider intelligence remain internal.
- Client private data is workspace-only and is not present in the default fixtures or report.
- Client-safe summaries, blockers, evidence requirements, approval requests, next actions, and reviewed professional packets are export candidates.
- Global intelligence can leave the core only as an approved aggregated/redacted summary.

Clone manifests are curated projections. They list source references, client-visible references, excluded modules and fields, policy packs, retention, redaction, and review requirements. No clone copies code or creates a tenant.

## Leakage and gates

The deterministic leakage checker scans metadata-shaped input for internal classes, cross-client markers, secret-like keys, raw HTML, and unredacted professional packets. Findings are metadata-only and fail closed. TrustOS gate actions include `client_workspace_export`, `client_clone_generation`, professional packet exports, `client_workspace_activation`, and `multi_client_workspace_access`.

Internal leakage, source-code exposure, prompt/formula exposure, and cross-client leakage hard-block. Professional packets require review. Safe summaries can be allowed as projections. The existing TrustOS action vocabulary and service-package vocabulary are reused; no second approval or evidence engine is introduced.

## Service packages

Trust Readiness Snapshot, Public Launch Readiness Pack, AI Agent Safety & Governance Audit, Ecommerce Compliance Readiness, Provider/Vendor Risk Review, Monthly TrustOps Retainer, CompanyOS Setup, MarketOS Growth Retainer, and Full MarketOS Managed OS map to workspace types and client-visible exports. Internal upsell strategy remains internal; clients receive safe next actions and approved deliverable references.

## Commands and safety

```text
python scripts/run_client_workspace_isolation.py --json
python scripts/run_client_workspace_isolation.py --workspace-type client_trustops_workspace --markdown
python scripts/run_client_workspace_isolation.py --clone-type trustops_readiness_clone --markdown
python scripts/run_client_workspace_isolation.py --check-leakage --markdown
python scripts/run_client_workspace_isolation.py --output artifacts/client_workspace_isolation/latest --markdown
```

Default execution is deterministic and offline. It performs no database writes, auth calls, tenant creation, network calls, provider calls, or artifact writes without `--output`. Future authentication, database tenancy, and RLS work must consume these policies and remain behind TrustOS review.
