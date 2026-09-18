# Bounded Source Dossier: DuckDB

## Repository Identification
- **Repository URL**: `https://github.com/duckdb/duckdb`
- **Pinned Commit SHA**: `19864453f7d0ed095256d848b46e7b8630989bac`
- **Pinned Release / Tag**: `v1.1.3`
- **License**: `MIT`

## License & Attribution Obligations
- **Attribution Obligations**: Retain MIT copyright notice in source and binary forms.
- **Dependency & License Risks**: Highly permissive. C++ native extension wheel (duckdb), minimal transitive dependencies.

## Technical Profile
- **Security & Advisory Status**: Clean. Extensive fuzzing and security sanitizers.
- **Supported Runtimes**: In-process C++, Python, Node, WebAssembly, cross-platform.
- **Tests & Maturity**: Very mature analytical engine; ubiquitous local analytical SQL standard.
- **Data & Network Behavior**: Default offline in-process single-file/in-memory database. Zero network unless httpfs extension is loaded.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.analytics.embedded_query_engine (offline analytical SQL over parquet/jsonl evidence).`
- **Adoption Decision**: `adapt`
- **Vendor / Wrap / Study Classification**: `studied / adapt (embedded analytical query reference).`
- **Rollback / Deactivation Strategy**: Revert to Python sqlite3 or in-memory filtering.
- **Operator Approval Requirement**: Offline in-process read is pre-cleared; network httpfs extension requires approval.
