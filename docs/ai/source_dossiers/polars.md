# Bounded Source Dossier: Polars

## Repository Identification
- **Repository URL**: `https://github.com/pola-rs/polars`
- **Pinned Commit SHA**: `87feed72585eff5acf3defb7f81029123d5cba68`
- **Pinned Release / Tag**: `py-1.17.1`
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
