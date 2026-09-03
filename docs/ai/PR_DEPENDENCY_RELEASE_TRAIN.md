# PR Dependency Release Train

This matrix establishes the strict sequencing for integrating and merging active MarketOS PR families to guarantee isolation and baseline health.

## Explicit Train Sequence

1. **Quality:** Baseline Repair PR is MERGED (#221).
2. **Security & Governance:** Secure artifact path traversal (#211) and MarketOS integration release contract (#223).
3. **Frontend/API:** Establish reproducible API boundary (#213) and Cloud Agent dev environment (#214).
4. **Research Adapters:** Adopt SerpApi for offline organic search & research projections (#224, duplicate handling for SerpApi PRs versus merged #219, Reddit branches).
5. **Commerce Operations:** Offline commerce readiness composition and decision packet (#225).
6. **Learning Ledger:** Recover deterministic training signals and learning influence (#226).
7. **Adversarial Evidence & Validation:** Test-only exposing production defects (#227) and Windows runner evidence manifest (#228).
8. **TrustOS & Extensibility:** New structural extensions and newly observed branches (Claude pipelines, TrustOS export, #230).

*Note: Any new external capability must align at the end of this release train unless explicitly promoted by an operator.*
