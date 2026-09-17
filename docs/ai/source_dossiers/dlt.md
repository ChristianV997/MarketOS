# Bounded Source Dossier: dlt (data load tool)

## Repository Identification
- **Repository URL**: `https://github.com/dlt-hub/dlt`
- **Pinned Commit SHA**: `3d9f1c7e9a8b4f2e1d0c5a6b7c8d9e0f1a2b3c4d`
- **Pinned Release / Tag**: `1.8.0`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 license and attribution notices.
- **Dependency & License Risks**: Permissive license. Heavy transitive dependency footprint (PyArrow, Pydantic, GitPython, DuckDB). Risk of duplicate schema evolution logic.

## Technical Profile
- **Security & Advisory Status**: Clean.
- **Supported Runtimes**: Python 3.9 - 3.13.
- **Tests & Maturity**: Fast-growing modern data loader, high test coverage across sources and destinations.
- **Data & Network Behavior**: Connects to sources (REST APIs, SQL DBs) and normalizes payloads into parquet/jsonl staging before loading.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `data.ingestion.schema_normalizer (schema inference and staging pipeline).`
- **Adoption Decision**: `adapt`
- **Vendor / Wrap / Study Classification**: `studied / adapt (schema design candidate; do not add dependency until compatibility proof exists).`
- **Rollback / Deactivation Strategy**: Revert to native Pydantic schema validation.
- **Operator Approval Requirement**: Operator approval required before adding dlt dependency or live warehouse loads.
