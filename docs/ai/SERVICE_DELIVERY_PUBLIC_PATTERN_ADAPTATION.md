# Public pattern adaptation — service delivery plane

Concepts only. No vendor copy, no framework install.

| Source | Version / commit | License | Pattern | Compatibility | Security | Decision | Rejected alternative |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pydantic typed-contracts idea (https://github.com/pydantic/pydantic) | v2.11 line / concept | MIT | Fail-closed typed packets and enums | Compatible as dataclasses + explicit schema strings | Low if secrets stay out of models | Reimplement as stdlib dataclasses (`MarketOS.ServiceDelivery.v1`) | Vendoring Pydantic into CompanyOS |
| OpenLineage (https://github.com/OpenLineage/OpenLineage) | 1.53.0 (tag 8ad5c14, 2026-09-01) | Apache-2.0 | Input/output provenance facets | Compatible as evidence_references + artifact_id | Medium if raw payloads leak | Record evidence refs and workspace-bound artifact IDs only | Installing openlineage-python |
| Great Expectations (https://github.com/great-expectations/great_expectations) | Apache-2.0 mainline | Apache-2.0 | Deterministic expectation states | Compatible as QUALITY_STATES | Low | Reimplement adequacy/partial/stale/conflict/insufficient/blocked/unavailable | Running GE suites against client data |
| Open Policy Agent (https://github.com/open-policy-agent/opa) | Apache-2.0 | Apache-2.0 | Default-deny transitions | Compatible as ALLOWED_TRANSITIONS | Low | Explicit allow-set; unknown transition raises | Embedding OPA runtime |
| OpenTelemetry (https://github.com/open-telemetry/opentelemetry-python) | Apache-2.0 | Apache-2.0 | Run metadata, not traces-as-payloads | Compatible as generated_at / record_kind | Medium if traces exported | Timestamp + planning record only; traces forbidden in export | Shipping OTEL exporters |
| TrustOS client_workspace_isolation (in-repo) | origin/main df59a060 | MarketOS | Workspace isolation + redaction | Required authority | High if bypassed | Consume, do not fork | Second isolation catalog |

Maintenance cost: four new files only. Catalog, finance planner, and TrustOS
remain the owners of their domains.
