# Bounded Source Dossier: Scrapy

## Repository Identification
- **Repository URL**: `https://github.com/scrapy/scrapy`
- **Pinned Commit SHA**: `2c7b5b5c98d6f51f5c6e838e5c46e32d5e786b3e`
- **Pinned Release / Tag**: `2.12.0`
- **License**: `BSD-3-Clause`

## License & Attribution Obligations
- **Attribution Obligations**: Retain BSD-3-Clause copyright notice and disclaimer in binary and source distributions.
- **Dependency & License Risks**: Low license risk (permissive BSD). Severe architectural risk: Twisted event loop conflicts with asyncio and MarketOS event spine.

## Technical Profile
- **Security & Advisory Status**: Clean. Maintained upstream with regular security releases.
- **Supported Runtimes**: Python 3.9 - 3.13, CPython.
- **Tests & Maturity**: Very mature (15+ years), battle-tested crawling engine.
- **Data & Network Behavior**: High-volume concurrent HTTP/HTTPS crawling with downloader middlewares.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.scouting.item_pipeline (selector syntax and clean Item validation pipeline design).`
- **Adoption Decision**: `emulate`
- **Vendor / Wrap / Study Classification**: `studied (design reference only; do not import Twisted engine).`
- **Rollback / Deactivation Strategy**: N/A (emulated design pattern, zero external dependency).
- **Operator Approval Requirement**: None for pattern emulation; operator approval required if live network scraping is ever considered.
