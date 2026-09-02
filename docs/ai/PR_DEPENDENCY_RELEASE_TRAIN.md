# PR Dependency Release Train

This matrix establishes the strict sequencing for integrating and merging active MarketOS PR families to guarantee isolation and baseline health.

## Explicit Train Sequence

1. **Quality:** Restore `main` branch test health, fix SBOM failures, stabilize CI runner (#221, Baseline Repair PR). Must merge first.
2. **Security:** Secure artifact path traversal & workspace escape (#211).
3. **Frontend/API:** Establish reproducible API boundary (#213).
4. **Development Environment:** Introduce Cloud Agent dev environment (#214). Strictly dependent on frontend/API.
5. **Research Adapters:** Adopt SerpApi for offline organic search & research projections (#220, #222).
6. **Commerce Operations:** Offline commerce readiness composition (#225).
7. **Evidence Integrity:** MarketOS operational governance, integration acceptance standards, and evidence integrity models (#223, #224).
8. **Learning Ledger:** Recover deterministic training signals (#226).

*Note: Any new external capability must align at the end of this release train unless explicitly promoted by an operator.*
