# PR Dependency Release Train

This matrix establishes the strict sequencing for integrating and merging active MarketOS PR families to guarantee isolation and baseline health.

## Explicit Train Sequence

1. **Quality:** Baseline Repair PR is MERGED (#221).
2. **Security & Governance:** Secure artifact path traversal (#211) and MarketOS integration release contract (#223).
3. **Production Repairs & Stacked Features:** Production repairs (#229) and its dependent stacked feature (#230).
4. **Frontend/API:** Establish reproducible API boundary (#213) and Cloud Agent dev environment (#214).
5. **Research & Supplier Surfaces:** Adopt SerpApi for offline organic search & research projections (#224, duplicate handling), along with new security (#231) and supplier (#237) surfaces.
6. **Commerce Operations:** Offline commerce readiness composition and decision packet (#225, currently behind main/stale base).
7. **Learning Ledger:** Recover deterministic training signals and learning influence (#226).
8. **Adversarial Evidence & Validation:** Test-only exposing production defects (#227) and Windows runner evidence manifest (#228).

*Note: Any new external capability must align at the end of this release train unless explicitly promoted by an operator.*
