# Public pattern adaptation — service delivery plane

Concepts only. No vendor copy, no framework install.

| Source | Version / URL | License | Pattern taken | Why source was not copied |
| --- | --- | --- | --- | --- |
| Odoo Community project/service | 18.0 docs, https://github.com/odoo/odoo | LGPLv3 | Engagement as a scoped project with stages and planned vs consumed hours | LGPLv3 copyleft; MarketOS cannot vendor Odoo models |
| Dolibarr proposals/projects | 21.0 line, https://github.com/Dolibarr/dolibarr | GPLv3 | Proposal → project → deliverable acceptance without auto-invoicing | GPLv3 copyleft; only the stage idea is reused |
| OpenLineage | 1.53.0, https://github.com/OpenLineage/OpenLineage | Apache-2.0 | Job/run/input-output facet as evidence_references + artifact_id | No openlineage-python dependency |
| Great Expectations | current mainline, https://github.com/great-expectations/great_expectations | Apache-2.0 | Deterministic expectation states | QUALITY_STATES reimplemented; GE suites not executed on client data |
| Open Policy Agent | current, https://github.com/open-policy-agent/opa | Apache-2.0 | Default-deny allow-set | ALLOWED_TRANSITIONS + TRANSITION_APPROVER; no OPA runtime |
| Metabase question/snapshot | OSS docs, https://github.com/metabase/metabase | AGPLv3 | Client export is a frozen snapshot, not a live query | AGPL; snapshot idea only |
| OpenTelemetry | current, https://github.com/open-telemetry/opentelemetry-python | Apache-2.0 | Run metadata, not traces-as-payloads | generated_at + record_kind only |
| TrustOS client_workspace_isolation | origin/main df59a060 | MarketOS | Workspace isolation + redaction | Consumed, not forked |

Duplicate-authority note: `#261` (`evaluation/companyos/service_delivery.py`)
imports `backend.economics.kernel` and `backend.workspaces`, which are not
on origin/main. This lane stays on `#260` files only and does not merge
or duplicate that module.
