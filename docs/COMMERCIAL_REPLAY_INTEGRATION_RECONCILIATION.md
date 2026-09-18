# Commercial Replay Integration — Dependency Reconciliation

Lane: `COMMERCIAL-REPLAY-INTEGRATION-V3`. This PR supersedes **PR #256**
("test(system): cross-system commercial dry-run replay integration
harness") for the reason below. **Close #256 in favor of this PR** once
this one is reviewed; do not run both.

## Why #256 could not be updated in place

#256 (`claude/commercial-dry-run-replay-integration-v1`) is branched from
PR #250's commit (`claude/marketos-commerce-integration-23e6gj` @
`f48dfb1`). #250 independently introduces `backend/economics/kernel.py` —
**byte-for-byte identical** to the same file already introduced by PR #248
(`codex/marketos-profit-evidence-kernel-v1`). Confirmed:

```
diff <(git show origin/codex/marketos-profit-evidence-kernel-v1:backend/economics/kernel.py) \
     <(git show origin/claude/marketos-commerce-integration-23e6gj:backend/economics/kernel.py)
# (no output — identical)
```

`backend/economics/__init__.py` and `docs/FINANCIAL_EVIDENCE_KERNEL.md` are
also identical between the two PRs. `tests/test_financial_economics_kernel.py`
differs by exactly one test: #250's version explicitly comments that it
deliberately omits the `MarketLane`-aware `supplier_feasibility.py` test
because that file is "PR #248's... integration to land" — direct evidence
#250's author built on top of #248's kernel, then vendored a copy of it
rather than depending on #248 directly.

Rewriting #256 to depend on #248 instead of #250 would require moving its
branch's parent commit, which is a rebase/force-push — explicitly
prohibited by this mission's instructions. **This PR is the authorized
"clean replacement" alternative** named in the mission brief for exactly
this situation.

## What this PR keeps from #250 (and why each file is not a duplicate)

Excluded (duplicates of #248, already present via this PR's base):
`backend/economics/kernel.py`, `backend/economics/__init__.py`,
`docs/FINANCIAL_EVIDENCE_KERNEL.md`, `tests/test_financial_economics_kernel.py`.

Kept (#250's unique, non-duplicate value — verified to import and pass
unchanged against #248's byte-identical kernel):

- `evaluation/commerce/canonical.py` — competitive evidence, business-model
  ownership accountability, promotion risk state. Its own docstring already
  disclaims re-deriving money/evidence/product concepts.
- `evaluation/commerce/business_model_economics.py` — business-model-aware
  dispatch into the kernel's `calculate_unit_economics`; no formula
  reimplemented.
- `evaluation/commerce/promotion.py` — the promotion-gate state machine
  (evidence-state ceilings).
- `evaluation/commerce/dry_run_lifecycle.py` / `dry_run_scenarios.py` — the
  15-step dry-run lifecycle and 5 named scenarios (hydroponics, smart pet,
  solar 4G blocked, commodity electronics rejected, high-ticket deferred) —
  these are the mission's required scenarios 1-5, already built.
- `evaluation/companyos/service_engagement.py` — client-facing wrapper over
  `ServicePackage` for the four sellable services, used by #256's own test
  file to build the mission's scenarios 6-7 (service client with
  inadequate/adequate data).
- `tests/commerce_canonical/*` — 43 tests, all passing unchanged.

Kept from #256 itself (its actual unique contribution):

- `evaluation/commerce/dry_run_events.py` — an `Event` projection over
  `DryRunLifecycleReport`, following the existing `evaluation.commerce.service.evaluation_events`
  pattern.
- `tests/system/test_commercial_dry_run_replay_integration.py` — 31 passing
  integration tests + 1 documented `xfail` (the already-tracked PR #211
  artifact-store escape, reproduced here as a `strict` `xfail`, not
  re-fixed — that fix remains #211's owned scope).

**Result: 176 passed, 1 xfailed**, identical pass count to what #256
reported against its (duplicate) dependency, now running against the
canonical, non-duplicate one.

## New: filling 3 evidence-truth gaps (mission section F)

`tests/system/test_commercial_replay_evidence_truth_gaps.py` (5 new tests)
covers three mission-required invariants #256's own suite did not yet
assert, reusing existing canonical authorities only:

- an executed-but-failed CoderOS probe (non-zero exit, malformed output)
  is never silently downgraded to the weaker `unavailable` state, and
  `unavailable` never reads as a pass (`backend.adapters.coderos_readonly.probe`);
  reproduced with real (bounded, local, no-network) subprocess execution.
- a supplier catalog listing / fully-supplied fixture evidence never grants
  `create_order` approval (`evaluation.trustos.gate_runner.evaluate_action`).

## A newly discovered, out-of-scope duplicate (reported, not fixed here)

While verifying `service_engagement.py`, this review found it defines its
own `ClientServiceDefinition` wrapper over the same four service packages
that a **separate, unrelated PR** (`#261`, "feat(companyos): add
service-delivery client engagement plane", not part of this mission's
scope) also wraps via its own `ClientFacingServicePackage`. Neither #250
nor #261 knew about the other at authoring time. This is **not fixed in
this PR** — reconciling it would pull an unrelated, independently-scoped
PR into this one's blast radius, and #261 is not part of this mission's
assigned PR list (#256, #255). Flagging it here for a future, explicitly-
scoped reconciliation pass, consistent with "do not create a competing
duplicate PR" for THIS mission while still being honest about what was
found.

## Rollback

This PR's only production code is unchanged-since-#250 (Money/kernel usage
verified identical) plus one new file (`dry_run_events.py`, unchanged from
#256) plus one new test file. `git revert` of this PR's commit(s) is clean;
nothing outside these files is touched.
