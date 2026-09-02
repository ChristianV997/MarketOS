# PR Dependency Release Train

This matrix establishes the strict sequencing for integrating and merging active MarketOS PR families to guarantee isolation and baseline health.

## Explicit Train Sequence

1. **Quality / Baseline:** Restore `main` branch test health, fix SBOM failures, stabilize CI runner (#221, Baseline Repair PR). Must merge first.
2. **Artifact Security:** Secure artifact path traversal & workspace escape (#211).
3. **Frontend/API:** Establish reproducible API boundary (#213).
4. **Environment:** Introduce Cloud Agent dev environment (#214). Strictly dependent on frontend/API.
5. **Provider Projections:** Adopt SerpApi for offline organic search & commerce projections (#220, #222).
6. **Governance / Adoption:** MarketOS operational governance, integration acceptance standards, and external capability adoption map (#223, #224).
7. **Commerce Operations:** Offline commerce readiness composition (#225).
8. **Learning Ledger:** Recover deterministic training signals (#226).

*Note: Any new external capability must align at the end of this release train unless explicitly promoted by an operator.*
