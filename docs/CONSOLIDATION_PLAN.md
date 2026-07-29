# MarketOS — Consolidation Plan (retired)

This document described a point-in-time audit of the repository (branch
`claude/analyze-repository-fsGUx`, pre-Tier-0). It is now materially
wrong and has been retired rather than kept around to mislead future
work:

- It claimed the cognitive shadow system (`backend/memory/`,
  `backend/vector/`, `backend/lineage/`, `backend/runtime/sleep/`) was
  orphaned. It is not — it has live callers in `orchestrator/main.py`
  and `backend/execution/loop.py`.
- It described duplicate integration layers (two Shopify clients, two
  Adobe AJO clients, two Supabase connectors, a disjoint TikTok creative
  surface) that have since been consolidated to one implementation each
  (Tier 0 of the build-vs-buy roadmap).
- It referenced modules that no longer exist
  (`connectors/adobe_ajo_connector.py`, `connectors/supabase_connector.py`).

For the current state of the codebase, read the code directly — start
from `orchestrator/main.py`'s phase dispatch table (`_PHASE_WORKERS`) and
`backend/api.py` / `api/routes/*.py` for the live spine, and
`backend/memory/`, `backend/vector/`, `backend/lineage/`,
`backend/runtime/sleep/` for the cognitive subsystem now wired into it.

Three calibration modules coexist deliberately, not as unreconciled
duplication:
- `backend/learning/calibration.py` — online prediction bias/uncertainty
  correction (holdout-split, shadow-gated).
- `backend/learning/world_model_calibration.py` — Bayesian bias/scale
  update for the world model specifically.
- `simulation/calibration.py` — the audit/dashboard trail: records every
  (predicted, actual) pair and exposes MAE/RMSE/bias summaries; distinct
  from `simulation/calibrator.py`, which applies the correction.
