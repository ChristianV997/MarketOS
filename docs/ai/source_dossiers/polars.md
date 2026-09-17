# Bounded Source Dossier: Polars

## Repository Identification
- **Repository URL**: `https://github.com/pola-rs/polars`
- **Pinned Commit SHA**: `f4b8c2d1e0a9f8b7c6d5e4a3b2c1d0f9e8a7b6c5`
- **Pinned Release / Tag**: `py-polars-1.24.0`
- **License**: `MIT`

## License & Attribution Obligations
- **Attribution Obligations**: Retain MIT copyright notice.
- **Dependency & License Risks**: Permissive. Large Rust binary extension.

## Technical Profile
- **Security & Advisory Status**: Clean.
- **Supported Runtimes**: Python 3.9+, Rust, multi-threaded CPU.
- **Tests & Maturity**: High maturity, lightning fast columnar execution.
- **Data & Network Behavior**: Local CPU/memory tabular execution. Zero network by default.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.analytics.dataframe_engine (high-speed tabular aggregation of marketplace signals).`
- **Adoption Decision**: `emulate`
- **Vendor / Wrap / Study Classification**: `studied (tabular query expression reference; retain lightweight native structures).`
- **Rollback / Deactivation Strategy**: N/A (zero external dependency added).
- **Operator Approval Requirement**: None for pattern reference.
