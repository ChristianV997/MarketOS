# Bounded Source Dossier: Great Expectations

## Repository Identification
- **Repository URL**: `https://github.com/great-expectations/great_expectations`
- **Pinned Commit SHA**: `883fd69e62d44fde0db8c61e300305a4f678b87f`
- **Pinned Release / Tag**: `1.3.0`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 notice and copyright.
- **Dependency & License Risks**: Permissive license. Enormous dependency graph (Pandas, Jinja2, Cryptography, Ruamel.yaml, Click, etc.).

## Technical Profile
- **Security & Advisory Status**: Clean.
- **Supported Runtimes**: Python 3.9 - 3.12.
- **Tests & Maturity**: Very mature, widely adopted data quality suite.
- **Data & Network Behavior**: Local dataset assertion against data stores.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `evaluation.data_quality.expectations (fixture and payload contract validation).`
- **Adoption Decision**: `emulate`
- **Vendor / Wrap / Study Classification**: `studied (assertion DSL emulated; reject full framework).`
- **Rollback / Deactivation Strategy**: Standard pytest assertions.
- **Operator Approval Requirement**: None for lightweight assertion functions.
