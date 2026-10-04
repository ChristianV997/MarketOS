# Site Draft Builder — Evidence-Connected Vertical Slice

## Verified baseline (read by @hermes)
- origin/main SHA: `e697f1c0365115cba2e96ff857a953377d5d261d` (verified via git rev-parse)
- Clean worktree: `C:/Users/HP/Documents/MarketOS-site-draft-slice` (detached HEAD at e697f1c0)
- Canonical checkout left dirty/untouched: `C:/Users/HP/Documents/MarketOS` (HEAD 94a38ca)
- All 179 existing tests PASS on the clean worktree (pytest from scratch deps)

## Existing contract (present on main — NO missing dependency)
- Seam: `evaluation/commerce/site_draft_builder.py::build_site_draft_pack(...)`
  - kwargs: launch_draft_pack, opportunity_synthesis, product_validation,
    marketplace_trends, supplier_feasibility, consumer_attention,
    client_context, site_type
  - returns SiteDraftPack (dataclass, .to_dict())
- Upstream evidence producers (all on main):
  - `evaluation/commerce/launch_draft_pack.py::build_launch_draft_pack(...)`
  - `evaluation/commerce/opportunity_synthesis.py::build_product_opportunity_synthesis(...)`
  - `evaluation/commerce/marketplace_trends.py`, `supplier_feasibility.py`,
    `consumer_attention.py` (build_report)
  - `scripts/run_product_opportunity_synthesis.py::_default_reports()` (fixture pipeline)
- CLI: `scripts/generate_site_draft_pack.py` (already wires _defaults → synthesis → launch → site)
- Fixture dir: `tests/fixtures/site_draft_builder/` (15 files: per-site-type contexts,
  launch_draft_pack.json, opportunity_synthesis_report.json, supplier_feasibility_report.json,
  marketplace_trend_report.json, consumer_attention_report.json, negative cases)
- tests: `tests/test_site_draft_builder.py` (192 lines, 19 parametrized cases),
  `tests/test_site_draft_builder_cli.py` (92 lines, 9 cases)

## What the slice ADDS (owner: @marketos-code)
A single end-to-end fixture runner that:
1. Loads real fixture files from `tests/fixtures/site_draft_builder/` by name (preserves
   candidate/workspace identity — no synthesized defaults).
2. Feeds them through `build_site_draft_pack` with explicit provenance on every input.
3. Writes a sanitized export set (JSON + markdown) to a temp dir, preserving
   missing-vs-explicit-zero distinctions (evidence_mode and readiness blockers; supplier presence is
   carried by the readiness check, never by the shared `market_access` projection).
4. Asserts review blockers surface (supplier_proof_ready, publishing_authorized=False).
5. Prints a one-line SHA-validated manifest.

File ownership (NO overlap):
- @marketos-code: `scripts/run_site_draft_e2e.py` (new), edits only to
  `evaluation/commerce/site_draft_builder.py` if a real seam bug surfaces.
- @marketos-ops: `tests/test_site_draft_e2e.py` (new integration/acceptance tests).
- @marketos-orchestrator: plan + PR + integration coordination (this file + PR body).
- @marketos-research: read-only contract map (already done above).
- @hermes: adversarial contract review (read-only).

## Hard constraints (all bots)
- status stays "draft"; no CMS/storefront writes, hosting, publishing, analytics, ads,
  provider calls, credentials, live mutations.
- No new dependency or global install; use existing OSS only if already reviewed/pinned/licensed.
- Do NOT touch: supplier-feasibility importer; api/routes/canonical_events.py;
  Launch Draft Pack files; Shopify taxonomy files; requirements-test.txt; CI workflow.
- Do NOT touch the dirty canonical checkout or Batch 1 paths.
- If a stable source contract is missing on main, report it — do not copy an unmerged PR.
