# Bounded Source Dossier: OpenLineage

## Repository Identification
- **Repository URL**: `https://github.com/OpenLineage/OpenLineage`
- **Pinned Commit SHA**: `8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d`
- **Pinned Release / Tag**: `1.28.0`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 notice and copyright.
- **Dependency & License Risks**: Permissive license. Heavy ecosystem bindings (Spark, Flink, Airflow).

## Technical Profile
- **Security & Advisory Status**: Clean.
- **Supported Runtimes**: Python, Java, JSON-schema.
- **Tests & Maturity**: Linux Foundation standard for data lineage.
- **Data & Network Behavior**: Emits JSON events (Job, Dataset, Run) over HTTP to lineage backends.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.observability.lineage (provenance and facet schemas for evidence traceability).`
- **Adoption Decision**: `emulate`
- **Vendor / Wrap / Study Classification**: `studied (schema pattern emulated; do not pull in heavy emitter client).`
- **Rollback / Deactivation Strategy**: Native lightweight provenance dicts.
- **Operator Approval Requirement**: None for internal facet schemas.
