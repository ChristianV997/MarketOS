# Source-adaptation consolidation v1

Lane: `grok/marketos-source-adaptation-consolidation-v1`. Draft only. Do not merge.

## Audit findings

- `src-crawl4ai` targeted a non-existent module `backend.scouting.crawl4ai_client`. The live adapter is `backend/adapters/research/crawl4ai.py`.
- `src-higgsfield-gpu-orchestration` was deferred; GPU/cluster orchestration is rejected.
- `src-higgsfield-cli` tag `v0.3.1` was stale; public latest is `v1.1.25` at `dc7e2d2`.
- `src-coderos`, `src-gstack`, and `src-hermes-ecc` used sequential placeholder SHAs. Hermes pointed at a non-existent `ecc/hermes-agent-spec` repository.
- No duplicate `source_id` or repository URL. OpenLineage + Dagster correctly share the existing `backend.observability.lineage_facets` emulate authority.

## Corrections applied

- Retarget Crawl4AI to `backend.adapters.research.crawl4ai` (existing optional adapter; no new crawler runtime).
- Reject Higgsfield GPU orchestration.
- Pin CoderOS `b980e90b49ea7c0639094f3060ced5aaf772a571`, gstack `a6b3a57512ca6d5c6aa5b68f74f736195021f96e`, Hermes `027d1a8a6043355b7af53b4c0645336b41372b7b` on `NousResearch/hermes-agent` as `reference_only`.
- Validator now fails closed on the stale Crawl4AI authority and on GPU emulate/copy_pattern.

## One approved control

Emulate/reference only. No second registry, scanner, event spine, or provider. No AGPL/ELv2/Sustainable Use integration. No desktop MCP or GPU runtime.

## Validation not run here

No MarketOS worktree in this sandbox. Operator should run:

```
python scripts/ai/validate_source_adaptation_registry.py --summary
pytest tests/contracts/test_source_adaptation_governance.py tests/contracts/test_source_adaptation_consolidation_v1.py -q
python -m compileall evaluation/source_governance tests/contracts/test_source_adaptation_consolidation_v1.py
```

If the golden catalog hash assertion in `test_stable_hash_is_deterministic_and_bit_identical` still pins `b8007cb9`, update it to `653b26137303255485846d7395dc75555011457499838b2ef52e1ac96ca152ae` or drop the golden pin and keep the two-load equality check.
