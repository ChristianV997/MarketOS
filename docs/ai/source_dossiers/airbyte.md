# Bounded Source Dossier: Airbyte

## Repository Identification
- **Repository URL**: `https://github.com/airbytehq/airbyte`
- **Pinned Commit SHA**: `1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b`
- **Pinned Release / Tag**: `v0.64.0`
- **License**: `ELv2`

## License & Attribution Obligations
- **Attribution Obligations**: Cannot provide as managed service; source-available commercial restrictions.
- **Dependency & License Risks**: CRITICAL LICENSE & ARCHITECTURAL RISK: Non-OSI commercial restriction; Docker-in-Docker / Java orchestrator engine.

## Technical Profile
- **Security & Advisory Status**: Regular maintenance.
- **Supported Runtimes**: Java, Docker, Python connector CDK.
- **Tests & Maturity**: Very mature ELT platform.
- **Data & Network Behavior**: Massive bulk data replication across hundreds of databases and APIs.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `Data connector protocol.`
- **Adoption Decision**: `reject`
- **Vendor / Wrap / Study Classification**: `studied (study Airbyte Protocol record/schema spec as conceptual reference only).`
- **Rollback / Deactivation Strategy**: N/A (rejected for adoption).
- **Operator Approval Requirement**: Strict prohibition against embedding Airbyte runtime.
