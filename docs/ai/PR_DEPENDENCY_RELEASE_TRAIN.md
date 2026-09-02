# PR Dependency Release Train

This matrix establishes the strict sequencing for integrating and merging active MarketOS PR families to guarantee isolation and baseline health.

| PR Family / Domain | Primary Goal | Active PRs | Dependencies / Release Position |
|---|---|---|---|
| **Quality/Baseline** | Restore main branch test health, fix SBOM failures, stabilize CI runner | Baseline Repair PR (TBD), #221 | **Position 1 (Blocker)**. Must merge first before any feature branch. |
| **Artifact-Store Security** | Secure artifact path traversal & workspace escape | #211 | **Position 2**. Follows baseline repair. |
| **Frontend/API** | Establish reproducible API boundary | #213 | **Position 3**. Independent of backend security, but must clear baseline. |
| **Environment** | Introduce Cloud Agent dev environment | #214 | **Position 4 (Stacked)**. Strictly dependent on #213. Rebase required post-#213 merge. |
| **SerpApi Adapter/Projection** | Adopt SerpApi for offline organic search & commerce | #220 (Organic), #222 (Commerce) | **Position 5**. #222 strictly queues after #220. Must prove no DataForSEO double-counting. |
| **Commerce Operations** | Offline commerce readiness composition | #225 | **Position 6**. Integrates after foundational SerpApi commerce data is verified. |
| **Learning Ledger** | Recover deterministic training signals | #226 | **Position 7**. Operates on the stable features established by preceding merges. |
| **Capability Adoption** | Enforce integration acceptance standards for future SaaS/APIs | #224 | Parallel governance tracks. Merges asynchronously with PRs adhering to this track. |

*Note: Any new external capability must align at the end of this release train unless explicitly promoted by an operator.*
