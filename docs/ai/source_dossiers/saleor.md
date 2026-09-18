# Bounded Source Dossier: Saleor

## Repository Identification
- **Repository URL**: `https://github.com/saleor/saleor`
- **Pinned Commit SHA**: `a2a04538ed9e64bfee844179e672645d4fd3f6a5`
- **Pinned Release / Tag**: `3.20.91`
- **License**: `BSD-3-Clause`

## License & Attribution Obligations
- **Attribution Obligations**: Retain BSD-3-Clause notice and disclaimer.
- **Dependency & License Risks**: Permissive license. Heavy Django/PostgreSQL/GraphQL server stack.

## Technical Profile
- **Security & Advisory Status**: Clean.
- **Supported Runtimes**: Python 3.10 - 3.12.
- **Tests & Maturity**: Very mature enterprise headless commerce platform.
- **Data & Network Behavior**: GraphQL commerce backend, webhooks, payment gateways.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.commerce.saleor_adapter (Product attribute and multi-channel pricing schema).`
- **Adoption Decision**: `adapt`
- **Vendor / Wrap / Study Classification**: `studied / adapt (schema adapted; do not embed Django core).`
- **Rollback / Deactivation Strategy**: Revert to standard MarketOS product schema.
- **Operator Approval Requirement**: Live channel mutations require operator approval.
