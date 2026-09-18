# Bounded Source Dossier: Dagster

## Repository Identification
- **Repository URL**: `https://github.com/dagster-io/dagster`
- **Pinned Commit SHA**: `21db4e55d3d1b723be3fdd90690fb9ca638744ac`
- **Pinned Release / Tag**: `1.9.10`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 notice and copyright.
- **Dependency & License Risks**: Permissive license, but massive monorepo framework (Dagit web server, GraphQL API, gRPC daemon, SQLAlchemy, Alembic).

## Technical Profile
- **Security & Advisory Status**: Clean.
- **Supported Runtimes**: Python 3.9 - 3.12.
- **Tests & Maturity**: Highly mature, industry-standard data asset orchestrator.
- **Data & Network Behavior**: Asset materialization tracking against SQLite/PostgreSQL metadata store.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.observability.lineage_facets (software-defined asset tags and asset materialization lineage metadata).`
- **Adoption Decision**: `emulate`
- **Vendor / Wrap / Study Classification**: `studied (emulate software-defined asset lineage metadata; reject heavy Dagit/daemon runtime).`
- **Rollback / Deactivation Strategy**: Native lightweight dataclasses for asset metadata.
- **Operator Approval Requirement**: None for internal dataclasses.
