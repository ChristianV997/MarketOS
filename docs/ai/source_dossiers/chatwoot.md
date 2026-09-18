# Bounded Source Dossier: Chatwoot

## Repository Identification
- **Repository URL**: `https://github.com/chatwoot/chatwoot`
- **Pinned Commit SHA**: `9f920b549c14491a4e587687a3eed5d21c6ccc7d`
- **Pinned Release / Tag**: `v4.18.0`
- **License**: `AGPL-3.0`

## License & Attribution Obligations
- **Attribution Obligations**: Complete source code disclosure over network under AGPL-3.0 if distributed or served.
- **Dependency & License Risks**: CRITICAL LICENSE RISK: AGPL-3.0 is viral copyleft. Any linking, vendoring, or importing infects MarketOS. Ruby on Rails runtime.

## Technical Profile
- **Security & Advisory Status**: Regular CVE patches for web surface.
- **Supported Runtimes**: Ruby, Node, Redis, PostgreSQL.
- **Tests & Maturity**: Mature open-source customer engagement platform.
- **Data & Network Behavior**: Full multi-channel customer messaging server (WhatsApp, Email, LiveChat).

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `External customer communication gateway.`
- **Adoption Decision**: `reject`
- **Vendor / Wrap / Study Classification**: `studied (study API contract only; strict isolation; reject vendoring).`
- **Rollback / Deactivation Strategy**: N/A (rejected for adoption).
- **Operator Approval Requirement**: Mandatory operator review and network boundary isolation before any external webhooks.
