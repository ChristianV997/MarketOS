# High-Leverage Backlog

Updated: 2026-09-01

## Sequencing

1. **Baseline/Quality Recovery:** Fix `main` test-health, SBOM dependencies, and quality-gate CI semantics (#221).
2. **Artifact Security:** Implement artifact-store path traversal and identity binding security (#211).
3. **Learning Ledger Recovery:** Restore deterministic training signal mechanisms.
4. **Frontend/API:** Consolidate the frontend reproducible boundary (#213) and dev environments (#214).
5. **SerpApi:** Consolidate SerpApi organic request adapter (#220) and commerce projection (#222) ensuring strictly isolated, dry-run only, offline integration without DataForSEO double-counting.
6. **Future External Capability Adoption:** Must prove provenance, license, credentials, cost, timeout, retry, dry-run, health, evidence, and failure contracts before adoption by fully filling out `docs/ai/EXTERNAL_CAPABILITY_INTEGRATION_TEMPLATE.md` and adhering to `docs/ai/INTEGRATION_ACCEPTANCE_STANDARD.md`.

## Architectural Governance
- Prevent future duplicate routers, registries, schedulers, providers, and gates by extending singular root authorities (one event spine, one provider registry, one model-routing authority).

## Historical Directions
*(Note: Previous prioritization of Phase 1 offline marketplace trend slices, unauthenticated CJ probes, and legacy CompanyOS/TrustOS prompts are marked as historical context. Follow the active PR queue sequencing above.)*
