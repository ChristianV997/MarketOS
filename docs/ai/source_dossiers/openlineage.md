# Bounded Source Dossier: OpenLineage

## Repository Identification
- **Repository URL**: `https://github.com/OpenLineage/OpenLineage`
- **Pinned Commit SHA**: `e7a768ffef28b2dd011e2376d4c63267316b6584`
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
