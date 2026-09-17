# Bounded Source Dossier: Crawl4AI

## Repository Identification
- **Repository URL**: `https://github.com/unclecode/crawl4ai`
- **Pinned Commit SHA**: `b6e9c40db8c1f964c48a735629c5c2d398d36eb1`
- **Pinned Release / Tag**: `v0.9.2`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 copyright notice, license text, and NOTICE file in source or distributions.
- **Dependency & License Risks**: Low license risk (permissive Apache-2.0). Runtime risks include Playwright browser binaries, headless Chromium execution footprint, and asyncio loop management.

## Technical Profile
- **Security & Advisory Status**: Clean. No known unpatched CVEs in v0.9.2.
- **Supported Runtimes**: Python >=3.9, Linux, macOS, Windows.
- **Tests & Maturity**: High maturity; extensive test suite covering extraction, CSS/XPath selection, and markdown generation.
- **Data & Network Behavior**: Outbound HTTP/HTTPS requests to target URLs; headless browser DOM rendering; html-to-markdown conversion. Strictly offline-by-default in MarketOS via fixtures.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.scouting.crawl4ai_client (narrow content extraction interface).`
- **Adoption Decision**: `integrate`
- **Vendor / Wrap / Study Classification**: `wrapped (thin client wrapper; no unbounded crawling).`
- **Rollback / Deactivation Strategy**: Revert to static HTML parsing (BeautifulSoup/lxml) or offline fixture snapshot.
- **Operator Approval Requirement**: Mandatory operator approval and network gate before live web extraction; offline fixtures default.
