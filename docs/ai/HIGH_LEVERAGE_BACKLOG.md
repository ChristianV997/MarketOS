# High-Leverage Backlog

Updated: 2026-09-02

## Sequencing

All active PR merges and integration efforts must adhere strictly to the order defined in docs/ai/PR_DEPENDENCY_RELEASE_TRAIN.md and pass the validation checks in docs/ai/INTEGRATION_RELEASE_CONTRACT.md.

## Highest-Leverage Implementation Queue

Current agents should focus on the following priorities to clear the multi-PR backlog and achieve consolidation:
1. **Production & Stacked Safety:** Solidify baseline quality via production repairs (#229) and stacked governance (#230), secure artifact paths (#211), and unblock main branch integration (#223).
2. **Security & Supplier Surfaces:** Integrate new security (#231) and supplier (#237) surfaces alongside offline supplier integration adapters (e.g. SerpApi #224).
3. **Frontend Cockpit:** API boundaries and frontend/environment integrations (#213, #214).
4. **Commerce Composition:** Offline commerce operations and deterministic decision testing, currently resolving stale base checks (#225).
5. **Learning & Adversarial Integrity:** Solidify the learning ledger (#226) and handle adversarial production-defect test cases (#227).
6. **Windows Runner & Evidence Labeling:** Ensure cross-platform evidence validation for Windows runner environments and correct evidence mislabeling classifications (#228).
7. **Release Consolidation:** Maintain governance and systematically merge the dependency train.

## Architectural Governance
- Prevent future duplicate routers, registries, schedulers, providers, and gates by extending singular root authorities (one event spine, one provider registry, one model-routing authority).
