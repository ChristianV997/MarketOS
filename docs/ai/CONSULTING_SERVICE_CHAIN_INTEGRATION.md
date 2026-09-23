# Consulting Service Chain Integration

This integration branch (`claude/consulting-service-chain-integration-c3`)
combines the consulting-productization wave into one chain:

```
request/intake
  -> consulting_offers            (offer catalog + proposal/SOW draft, PR #317)
  -> consulting_engagement        (engagement orchestration, PR #310)
  -> consulting_economics         (per-service economics, PR #309)
  -> consulting_portfolio         (portfolio synthesis over persisted reports, PR #311)
  -> consulting_evidence_register (evidence lineage over persisted reports, PR #319)
  -> consulting_delivery          (secure client delivery packaging, PR #312 — partial)
```

Each stage is a disjoint package under `services/consulting_*`. They are
loosely coupled through the existing `backend.organization.report_registry`
(`CommercialReport` / `PortfolioReport`), the same pattern already used
elsewhere in MarketOS — not through direct function calls between stages.
`tests/services/test_consulting_service_chain/test_chain_smoke.py` proves
this composes for real: one shared `ClientWorkspace`, one `ArtifactStore`,
real `build_*` calls from five packages feeding a real
`package_consulting_deliverable` call, plus a fail-closed cross-workspace
rejection test.

## PRs merged in full (no conflicts, no duplicate authorities found)

- **#309** `services/consulting_economics` — reuses
  `backend.economics.kernel.calculate_service_economics`; no second
  economics authority.
- **#310** `services/consulting_engagement` — reuses registered
  `ClientWorkspace`/`ArtifactStore`/`ReportRegistry`/`ServiceContractRegistry`,
  `evaluation.companyos.service_delivery.create_engagement`, and
  `evaluation.trustos.client_workspace_isolation.export_client_evidence`.
  This is the canonical engagement lifecycle for this chain.
- **#311** `services/consulting_portfolio` — deterministic synthesis over
  persisted component-report facts; no second ranker.
- **#317** `services/consulting_offers` — the canonical offer catalog,
  built on the existing `evaluation.companyos.service_catalog.ServicePackage`
  / `package_map` and `evaluation.companyos.service_engagement
  .catalog_with_canonical_services`. This is the **one** consulting offer
  catalog for the chain.
- **#319** `services/consulting_evidence_register` — a generic,
  self-contained normalizer over persisted component-report envelopes
  (`report_id`/`fingerprint`/`workspace_id`/`service_name`/`facts`). It does
  **not** duplicate PR #316's `services/market_research_evidence`: #316 is
  specific to the four market-research pillar report shapes (marketplace,
  supplier, consumer attention, public-market benchmark) and computes
  field-level provenance/conflict detection on them; #319 ingests *any*
  already-computed component report (economics, engagement, offers, or a
  market-research report once wrapped) and only aggregates lineage/gaps/
  conflicts already present in the input — it performs no freshness or
  conflict computation of its own. No files or imports overlap between the
  two, and neither depends on the other.

## PR partially merged

- **#312** `services/consulting_delivery/{package.py,packager.py}` only.
  This composes `backend.deliverables.{package,registry}`,
  `backend.organization.{commercial_report,portfolio_report}`, and
  `evaluation.trustos.client_workspace_isolation.check_workspace_leakage`
  to package a client-safe deliverable from already-registered reports,
  with a real fail-closed cross-workspace check
  (`ValueError("cross_workspace_leakage")`) verified by this branch's own
  smoke test. This is the **one** delivery/TrustOS-export boundary kept
  from the Jules delivery/operations wave.

  Its `services/consulting_operations/{intake.py,readiness.py}` half is
  **excluded**: it defines its own hardcoded `KNOWN_PACKAGES` catalog
  (`strategy_review` / `market_validation` / `growth_audit`) — a second,
  undocumented consulting-offer catalog that never touches
  `evaluation.companyos.service_catalog` or PR #317's catalog at all.
  Keeping it would violate "one consulting offer catalog."

## PR excluded entirely

- **#313** `services/consulting_operations/{packager.py,readiness.py,schemas.py}`.
  Two independent problems, both confirmed by reading the actual diff
  (not inferred from the PR title):
  1. **Literal path collision with #312**: both PRs create
     `services/consulting_operations/__init__.py` and
     `services/consulting_operations/readiness.py`, each defining an
     `evaluate_consulting_readiness` function and a `ConsultingReadinessReport`
     class with different signatures and different fields. They cannot both
     be applied.
  2. **A second, standalone engagement schema**: #313's
     `schemas.ConsultingEngagement` is an independent dataclass with no
     import of `backend.workspaces`, `backend.organization`, or
     `evaluation.companyos` — it does not compose the canonical engagement
     lifecycle PR #310 already builds by properly reusing
     `evaluation.companyos.service_delivery.create_engagement`. Keeping
     #313 would violate "one engagement lifecycle" in addition to
     colliding on-disk with #312.

  #313's `packager.py` also duplicates #312's delivery-packaging role
  (`check_workspace_leakage` over a hand-rolled `ConsultingEngagement`
  input) without composing `CommercialReport`/`PortfolioReport`, so there
  is no part of #313 worth cherry-picking independently of the two
  problems above.

  `#308` and `#318` (supplier/logistics integration) were not consumed, as
  instructed — they are a separate lane.

## Canonical rules, verified on this branch

| Rule | Where enforced |
| --- | --- |
| One consulting offer catalog | `services/consulting_offers/catalog.py` only; #312's shadow catalog and #313 both excluded |
| One evidence register | `services/consulting_evidence_register` only; confirmed disjoint from #316 (different domain) |
| One engagement lifecycle | `services/consulting_engagement` only; #313's competing schema excluded |
| One portfolio synthesis | `services/consulting_portfolio` only |
| One delivery/readiness boundary (delivery half) | `services/consulting_delivery` only |
| One TrustOS export boundary | `check_workspace_leakage` / `export_client_evidence` reused by #310, #312, #317 — never reimplemented |
| No billing/quoting/CRM/messaging/ads/publishing/payment/orders/live providers | None of the retained packages perform network calls, credential use, or state mutation beyond local `ArtifactStore`/registries; verified by each package's own safety-summary fields (`read_only=True`, `network_calls=False`, `database_writes=False`) |
| Planning prices remain assumptions | `consulting_offers.PlanningPriceRange` and `consulting_economics`'s evidence-state-tagged cost fields |
| Missing != zero | `consulting_economics` preserves `evidence_state: "assumed"` vs `"observed"` per cost field; never coerces an absent figure to 0 |
| Workspace mismatch / cross-client leakage fail closed | `consulting_delivery.build_consulting_delivery` raises on a metadata-claimed workspace mismatch; `package_consulting_deliverable` raises `cross_workspace_leakage` on a report registered under a different workspace — both verified by this branch's smoke test |
| Artifact-store mismatch fail closed | `consulting_engagement.orchestrator` raises `artifact_workspace_boundary_rejected` when the supplied `ArtifactStore`'s bound workspace does not match the registered one — `test_artifact_store_identity_mismatch_is_rejected`, from #310's own kept suite |
| Offer catalog consumed through a real dependency, not copied | `services/consulting_engagement/schemas.py` imports `OFFER_IDS` directly from `services.consulting_offers` (identity-checked in `test_engagement_schema_imports_the_same_offer_ids_object_not_a_copy`) and validates `optional_upsell_recommendations` against it — a real cross-package dependency, no redefinition |
| One envelope schema for both "generic component report" consumers | `services.consulting_evidence_register.build_component_report_envelope` — see below |
| Readiness states remain blocked/review-required when evidence is insufficient | `consulting_offers.PROPOSAL_STATUSES = {draft_ready, needs_evidence, blocked}`; `consulting_delivery.ConsultingDeliveryPackage.status` defaults to, and is forced back to, `"review_required"` for any unrecognized value (`test_review_required_is_explicit`, `test_status_remains_review_required`) |

## Two gaps closed in a later commit on this branch

Both items below were originally documented here as open follow-up work.
Both are now fixed, on this branch, with tests — not deferred further.

**The `service`/`service_name` envelope mismatch is now normalized in one
place.** `consulting_portfolio.synthesize_portfolio` reads a component-report
envelope's `service` key; `consulting_evidence_register.build_evidence_register`
reads `service_name` on the same conceptual envelope, and additionally
requires `workspace_id` and a status from its own fixed vocabulary
(`completed|partial|unavailable|blocked|draft|empty`). Rather than
patching either consumer (which would risk becoming "another" evidence
register or portfolio synthesis authority), a single new function —
`services.consulting_evidence_register.build_component_report_envelope`
— builds one envelope dict carrying both `service` and `service_name`
(aliased to the same value) plus `workspace_id` and a validated status,
that both `synthesize_portfolio` and `build_evidence_register` accept
unmodified. `tests/services/test_consulting_evidence_register/test_component_report_envelope.py`
proves one envelope list satisfies both consumers at once, and
`tests/services/test_consulting_service_chain/test_chain_smoke.py` was
updated to build its envelopes through this function instead of two
hand-written dicts per report.

**Readiness** itself (the "readiness" stage named in the objective's chain)
still has no dedicated cross-stage authority on this branch — both #312's
and #313's readiness modules were rejected for the reasons above, and
building a new one is explicitly out of scope for this lane ("do not
create another... consulting catalog, engagement model, economics
service, portfolio service, evidence register, or delivery packager").
What each stage already reports (`consulting_offers.PROPOSAL_STATUSES`,
`consulting_delivery`'s forced `review_required` default) already
satisfies "the chain never silently claims readiness it hasn't earned";
a dedicated cross-stage readiness rollup remains a legitimate future PR,
not a defect in this one.

## Validation run on this branch

- `pytest tests/services/test_consulting_economics tests/services/test_consulting_engagement tests/services/test_consulting_portfolio tests/services/test_consulting_offers tests/services/test_consulting_evidence_register tests/services/test_consulting_delivery tests/services/test_consulting_service_chain -q` → **98 passed** (87 prior + 9 new: 4 offer-catalog-dependency tests, 5 component-report-envelope tests)
- `pytest tests/contracts/test_architecture_boundaries.py tests/services/ -q` → **313 passed**
- `python -m compileall -q backend api evaluation services scripts tests` → clean
- `ruff check` over every retained/added package and test directory → clean
- `git diff --check` → clean
- `python scripts/ai/session_start.py --json` / `select_tests.py --from-git --json` → changed paths match exactly, `unknown_fallback` lane
- `python scripts/ai/session_finish.py --dry-run` → 6 passed
- `python scripts/ai/run_local_quality_gate.py --from-git --execute --phase preflight` → `status: "configuration_error"`, driven entirely by sandbox-wide conditions (`python_interpreter_mismatch`, `unpinned_requirements_present`, `git_state:dirty`) with no mention of any file this branch touches
- `python scripts/ai/pr_readiness_report.py` → `merge_readiness: "clear"`, no blocking warnings
- Security: manual pass on all changed files — no `eval`/`exec`/`os.system`/`pickle`/`yaml.load`/`subprocess` anywhere in the changed code

## Rollback

Revert the integration branch's merge commits in reverse order, or drop the
package directories listed above. Each original PR (#309–#313, #317, #319)
remains open, untouched, and un-force-pushed; none of their source branches
were modified by this integration.

## Next action

1. Land this branch's five full packages + partial #312 delivery packager
   as the consulting chain's first mergeable slice.
2. Close or substantially rewrite #313 (and its successor #327, which
   continues the same contaminated `consulting_operations` branch)
   referencing this document — it collides on-disk with #312 and
   duplicates #310's engagement schema. Neither #313 nor #327 was
   consumed by, copied into, or otherwise touched by this branch.
3. Build a dedicated readiness stage on top of #317's catalog and #310's
   `ConsultingEngagementResult` instead of reviving either rejected
   `KNOWN_PACKAGES` table or standalone `ConsultingEngagement` schema —
   still the one missing stage of the chain, and out of scope for this
   lane to build (see "do not create another... " constraint).
