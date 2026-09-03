# High-Leverage Backlog

Updated: 2026-09-01

## Sequencing

All active PR merges and integration efforts must adhere strictly to the order defined in `docs/ai/PR_DEPENDENCY_RELEASE_TRAIN.md` and pass the validation checks in `docs/ai/INTEGRATION_RELEASE_CONTRACT.md`.

## Highest-Leverage Implementation Queue

Current agents should focus on the following priorities to clear the multi-PR backlog and achieve consolidation:
1. **Production First-Phase Safety:** Solidify baseline quality, secure artifact paths, and unblock the main branch integration.
2. **Supplier/Consumer Adapters:** Review and merge offline supplier integration adapters (e.g. SerpApi).
3. **Windows Runner:** Ensure cross-platform evidence validation for Windows runner environments.
4. **Commerce Composition:** Offline commerce operations and deterministic decision testing.
5. **Frontend Cockpit:** API boundaries and frontend/environment integrations.
6. **Release Consolidation:** Maintain governance and systematically merge the dependency train.

## Architectural Governance
- Prevent future duplicate routers, registries, schedulers, providers, and gates by extending singular root authorities (one event spine, one provider registry, one model-routing authority).
