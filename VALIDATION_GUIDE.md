# Phase 3 Validation Guide

## Overview

Phases 1–8 of the MarketOS ROI overhaul all ship behind environment flag gates and run in **shadow mode** by default. This means:

- Both legacy and new logic execute on every decision
- Results are journaled side-by-side to the event_store as `shadow_*` events
- The **legacy result** is returned (no real budget moves)
- After validation clears, the flag is flipped to return the new result instead

This guide explains how to:
1. Deploy with shadow-mode flags active
2. Run decision cycles to populate event_store
3. Analyze shadow events and validate each phase
4. Flip flags once validation passes

---

## Part 1: Deployment & Shadow-Mode Activation

### Shadow-Mode Flags

All nine flags default to `false`. To enable shadow-mode data collection, set these environment variables:

```bash
export CAPITAL_POLICY_LIVE=false         # Phase 2 — shadow mode
export DECISION_NORMALIZE_LIVE=false     # Phase 3 — shadow mode
export REGIME_DETECTION_LIVE=false       # Phase 4 — shadow mode
export RISK_ADAPTIVE_LIVE=false          # Phase 5 — shadow mode
export ECONOMICS_GEO_LIVE=false          # Phase 6 — shadow mode
export CREATIVE_FATIGUE_LIVE=false       # Phase 7 (fatigue) — shadow mode
export URGENCY_SCORING_LIVE=false        # Phase 7 (urgency) — shadow mode
export MONTE_CARLO_LIVE=false            # Phase 7 (simulation) — shadow mode
export ORGANIC_CHANNEL_LIVE=false        # Phase 8 — shadow mode
```

### Staged Deployment

**Stage 1: Shadow Mode (default)**
```bash
# Deploy to staging with all flags at defaults (false)
# System runs both legacy and new logic, journals both, returns legacy result
# Duration: 50–100 decision cycles (enough to collect validation data)

git checkout claude/analyze-repository-fsGUx
python -m pytest -xvs tests/test_shadow_validator.py  # verify framework
python backend/validation/validate_phases.py --check-event-count
# Inspect event_store; should be empty or show 0 events for all phases
```

**Stage 2: Run Decision Cycles**
```bash
# Boot the orchestrator/execution loop
# Let it make 50–100 real product decisions
# Each decision → shadow-mode journal entry

# Option A: Run via CLI or API
python backend/execution/loop.py --cycles 100

# Option B: Run via HTTP endpoint (if deployed)
curl -X POST http://localhost:5000/orchestrator/run \
  -H "Content-Type: application/json" \
  -d '{"cycles": 100}'

# Inspect event_store — should now have shadow_* events
python backend/validation/validate_phases.py --check-event-count
```

**Stage 3: Validate**
```bash
# Generate validation report
python backend/validation/validate_phases.py --output validation_report.json --summary

# Review report — check if each phase passed its success bar
cat validation_report.json | jq .phases
```

**Stage 4: Flag Flip (per phase)**

Once a phase's validation passes:
```bash
# Flip ONE flag to live (e.g., capital_policy)
export CAPITAL_POLICY_LIVE=true

# Re-deploy, run another 20–30 cycles
# New logic now returns real result (still journaled for continued monitoring)
# If problems emerge, flip back to false immediately
```

---

## Part 2: Validation Framework

### Running Validation

#### Option A: Full Report
```bash
python backend/validation/validate_phases.py --output report.json
cat report.json | jq .
```

#### Option B: Human-Readable Summary
```bash
python backend/validation/validate_phases.py --summary
```

Output example:
```
Validation Report (ts=1234567890.0)
Phases Passed: 6/8
Regressions Detected: 0

✓ PASS   capital_policy               (67 events)
         legacy_sharpe_mean           = 0.4200
         policy_sharpe_mean           = 0.4600
         sharpe_ratio_lift            = 0.0952
✓ PASS   decision_normalize           (82 events)
         legacy_score_roas_corr       = 0.4250
         policy_score_roas_corr       = 0.6180
         correlation_lift             = 0.1930
⚠ REGRESSION DETECTED
⚠ FAIL   regime_detection             (15 events)
         Recommendation: collect_more_data
```

#### Option C: Single Phase
```bash
python backend/validation/validate_phases.py --phase capital_policy --summary
```

#### Option D: Event Count Check (pre-validation)
```bash
# Check if enough events have been collected before running full validation
python backend/validation/validate_phases.py --check-event-count
```

Output:
```
Event counts per phase:
--------------------------------------------------------------
✓ capital_policy             67 events (min: 50)
✓ decision_normalize         82 events (min: 50)
⚠ regime_detection          15 events (min: 30)
⚠ adaptive_risk             8 events (min: 20)
✓ unit_economics           105 events (min: 50)
✓ creative_fatigue         41 events (min: 40)
✓ urgency_scoring          58 events (min: 50)
⚠ organic_channel          12 events (min: 30)
```

### Understanding Validation Criteria

Each phase has success criteria defined in `PHASE_CRITERIA` dict:

| Phase | Min Events | Metric | Success Bar |
|-------|-----------|--------|------------|
| `capital_policy` | 50 | sharpe_ratio_lift | ≥ 5% |
| `decision_normalize` | 50 | correlation_threshold | ≥ 0.60 |
| `regime_detection` | 30 | mae_delta | ≤ 0.0 (no regression) |
| `adaptive_risk` | 20 | drawdown_reduction_pct | ≥ 30% |
| `unit_economics` | 50 | ranking_accuracy_lift | ≥ 15% |
| `creative_fatigue` | 40 | detection_latency_days | ≤ 3.0 |
| `urgency_scoring` | 50 | correlation_threshold | ≥ 0.60 |
| `organic_channel` | 30 | organic_cac_ratio | ≤ 0.60 |

### Validation Workflow

```
Collect events (50+ per phase)
          ↓
Run validation framework
          ↓
        ↙         ↘
   All pass?     Regression?
      ↓              ↓
     Yes             No
      ↓              ↓
  Ready to      Investigate
   flip flag    (root cause)
      ↓              ↓
  Increase      Adjust
  confidence    criteria or
  threshold      fix code
      ↓              ↓
  Flip flag    Re-deploy
   (live=true)   & rerun
      ↓
   Deploy +
   monitor
```

---

## Part 3: Phase-Specific Validation Details

### Phase 2: Capital Allocation

**What it validates**: The new mean-variance QP allocation improves portfolio Sharpe ratio vs. legacy linear ROAS-share allocation.

**Success criterion**: `sharpe_ratio_lift ≥ 5%` on realized outcomes.

**How to interpret**:
- If `sharpe_ratio_lift = 0.07`, the new allocation achieved 7% better Sharpe ratio → **PASS**
- If `sharpe_ratio_lift = 0.02`, only 2% improvement → **FAIL** (below 5% bar)
- If `sharpe_ratio_lift < 0`, new allocation *worse* than legacy → **REGRESSION** (critical)

**Next step if FAIL**: 
- May need more cycles (n=50 is minimum; try n=100)
- Check if risk context (drawdown, capital) is being passed correctly
- Review group correlation settings (default ρ=0.5)

---

### Phase 3: Decision Normalization + LinUCB

**What it validates**: The new z-scored, precision-weighted decision formula has higher rank-ordering correlation with realized ROAS than the legacy unnormalized sum.

**Success criterion**: `correlation_threshold ≥ 0.60` and `correlation_lift ≥ 0`.

**How to interpret**:
- `legacy_score_roas_corr = 0.45`, `policy_score_roas_corr = 0.62` → **PASS** (0.62 ≥ 0.60)
- Both below 0.60 → likely signal quality issue (not a Phase 3 bug)
- `policy_corr < legacy_corr` → **REGRESSION** (review z-score implementation)

**Next step if FAIL**:
- Check that product features are in the LinUCB context vector
- Verify calibration (Phase 4) is working correctly — bad confidence hurts precision weighting
- May need 100+ cycles for rare products

---

### Phase 4: Calibration + Regime Detection

**What it validates**: The new train/holdout-split calibration and CUSUM changepoint detection maintain or improve prediction accuracy and flag regime shifts earlier.

**Success criteria**:
- `mae_delta ≤ 0.0` (new MAE no worse than old)
- `detection_latency_days ≤ 2.0` (detect regime shift ≥2 days before actual ROAS collapse)

**How to interpret**:
- `legacy_mae = 0.150`, `policy_mae = 0.145` → `mae_delta = -0.005` → **PASS** (improved)
- `policy_mae = 0.180` → `mae_delta = 0.030` → **REGRESSION** (regressed)
- `avg_detection_latency_days = 1.2` → **PASS** (flagged early)

**Next step if FAIL**:
- Regime detection latency tied to changepoint method (CUSUM); may need tuning (ARL₀/ARL₁)
- Calibration regression may indicate train/holdout split is cutting off live signal
- Review if products have enough history (n>20) to split meaningfully

---

### Phase 5: Adaptive Risk

**What it validates**: The new adaptive risk caps (drawdown, daily spend) prevent realized loss better than static caps and never violate the computed limit.

**Success criteria**:
- `drawdown_reduction_pct ≥ 30%` (prevent at least 30% of realized losses)
- `spend_cap_violations = 0` (never exceed computed daily limit)

**How to interpret**:
- `legacy_avg_drawdown = 0.28`, `policy_avg_drawdown = 0.18` → `drawdown_reduction_pct = 0.357` → **PASS** (35.7% reduction)
- Any `spend_cap_violations > 0` → **FAIL** (risk system failure; critical)
- Low reduction pct (< 30%) → need more drawdown events to collect (rarer than typical cycles)

**Next step if FAIL**:
- If spend cap violated: check that `backend/risk/config.py` values are being used
- If low reduction: need cycles that *include* a real market drawdown event (may need 100+ cycles or replay historical)
- Verify adaptive formula `λ_eff = λ0 · (1 + drawdown_frac / max_drawdown)` is correct

---

### Phase 6: Unit Economics

**What it validates**: The new product ranking (using geo-aware shipping, category return rates, and LTV) better predicts actual product profitability than the flat-12%-return, no-LTV model.

**Success criterion**: `ranking_accuracy_lift ≥ 15%` (new ranking 15% more predictive).

**How to interpret**:
- `legacy_ranking_corr = 0.50`, `policy_ranking_corr = 0.62` → `lift = 0.12` → **FAIL** (12% < 15% bar)
- `ranking_accuracy_lift = 0.18` → **PASS** (18% improvement)

**Next step if FAIL**:
- May need more diverse product set (50+ unique products across categories/geos)
- Check that category return rates are calibrated (if all default 12%, no signal)
- Verify LTV tracker is populated (needs repeat-order data; may be sparse early)

---

### Phase 7: Creative Fatigue & Urgency

**What it validates**: The new rolling-window fatigue detector flags declining creatives ≥3 days before the realized ROAS drop, and urgency scoring correlates with early-mover success.

**Success criteria**:
- `fatigue_detection_latency ≤ 3.0` days
- `urgency_score_correlation ≥ 0.60`

**How to interpret**:
- `avg_detection_latency_days = 2.1` → **PASS** (detected 2.1 days early)
- `urgency_score_correlation = 0.58` → **FAIL** (0.58 < 0.60)

**Next step if FAIL**:
- Fatigue: may need more declining-creative examples in the event stream
- Urgency: may need better velocity/saturation signals from discovery adapters

---

### Phase 8: Organic Channel

**What it validates**: The new organic seeding tracker shows organic CAC < 60% of paid CAC (cost-effective new channel).

**Success criterion**: `organic_cac_ratio ≤ 0.60`.

**How to interpret**:
- `avg_organic_cac_ratio = 0.45` → **PASS** (organic CAC is 45% of paid)
- `avg_organic_cac_ratio = 0.70` → **FAIL** (organic CAC is 70% of paid; not yet cost-effective)

**Next step if FAIL**:
- Manual validation: seed 5 creators for 1 product (beauty or consumables), track 30 days
- Organic channel is net-new; initial seeding strategy may need iteration
- Success bar (60%) is conservative; iterate on creator pool selection

---

## Part 4: Troubleshooting

### Problem: "collect_more_data" for all phases

**Cause**: event_store is empty or has < min_cycles events.

**Fix**:
```bash
# Check event_store path
echo $STATE_DIR
ls -lh state/workflow_executions.jsonl

# Run more cycles
python backend/execution/loop.py --cycles 100

# Verify events are being logged
python backend/validation/validate_phases.py --check-event-count
```

### Problem: Validation framework crashes

**Cause**: event_store file exists but is malformed (torn JSON lines).

**Fix**:
```bash
# Event store reader skips malformed lines, but first check format
head -20 state/workflow_executions.jsonl | python -m json.tool

# If consistently failing, clear and re-run
rm state/workflow_executions.jsonl
python backend/execution/loop.py --cycles 50
```

### Problem: Regression detected in capital_policy

**Cause**: New allocation is worse than legacy on realized outcomes.

**Fix**:
1. **Check risk context**: New QP uses `risk_context` to scale λ. If context is stale/zero, QP defaults to base lambda.
   ```python
   # In capital_policy.py, line ~234
   policy = allocate_capital(arms, total_budget, risk_context=risk_context)
   # Verify risk_context is passed with capital/peak_capital fields
   ```

2. **Check group correlation**: Default ρ=0.5 (arms in same group treated as 50% correlated). If products are actually uncorrelated, increase ρ; if over-correlated, decrease.

3. **Check solver selection**: QP (CLARABEL/OSQP) should dominate. If falling back to LP, covariance penalty is lost.
   ```bash
   # Enable debug logging to see solver path
   RUST_LOG=debug python backend/validation/validate_phases.py
   ```

### Problem: Different validation results on re-run

**Cause**: Randomness in Monte Carlo (Phase 7) or bootstrap (validation itself).

**Fix**: Validation uses numpy seeding for reproducibility. If results differ:
1. Check event_store wasn't modified between runs
2. Ensure same model/env (changes to production code change validation results)
3. Increase sample size (more cycles → more stable metrics)

---

## Part 5: Flag-Flip Decision Tree

```
Does validation PASS for phase X?
│
├─ YES → Ready to flip
│  ├─ Phase 2 (capital)? → Set CAPITAL_POLICY_LIVE=true
│  ├─ Phase 3 (score)?  → Set DECISION_NORMALIZE_LIVE=true
│  ├─ Phase 4 (calib)?  → Set REGIME_DETECTION_LIVE=true
│  ├─ Phase 5 (risk)?   → Set RISK_ADAPTIVE_LIVE=true
│  ├─ Phase 6 (econ)?   → Set ECONOMICS_GEO_LIVE=true
│  ├─ Phase 7 (creat)?  → Set CREATIVE_FATIGUE_LIVE=true
│  │                    → Set URGENCY_SCORING_LIVE=true
│  │                    → Set MONTE_CARLO_LIVE=true
│  └─ Phase 8 (org)?    → Set ORGANIC_CHANNEL_LIVE=true
│
│  Then re-deploy and run 20–30 cycles in "live" mode
│  Monitor for production issues; revert flag if problems emerge
│
└─ NO → Stay in shadow mode
   ├─ Regression detected?
   │  └─ Investigate root cause
   │     ├─ Bad parameters? → Tune (e.g., λ0, ρ)
   │     ├─ Missing context? → Wire in missing signals
   │     └─ Algorithm bug? → Review implementation vs. design doc
   │
   ├─ Insufficient events?
   │  └─ Run more cycles (aim for 100+ before re-validating)
   │
   └─ Metric just-below threshold?
      └─ May be acceptable with business approval
         Example: decision_normalize ρ = 0.58 (threshold 0.60)
         → Revisit after Phase 4 improves calibration
```

---

## Part 6: Production Monitoring (Post Flag-Flip)

Once a flag is live, monitoring continues:

```bash
# Run validation monthly or after major code changes
python backend/validation/validate_phases.py --output validation_monthly.json

# Alert if any previously-passing phase regresses
python backend/validation/shadow_validator.py --compare validation_baseline.json validation_current.json
# (comparison tool TBD, but framework supports it)
```

Shadow-mode events are **still logged** even when flag is live, so you have a continuous audit trail of both legacy and new logic for regulatory/audit purposes.

---

## Summary

**Next Steps**:

1. **Deploy to staging** with all flags at defaults (false = shadow mode)
2. **Run 50–100 decision cycles** to populate event_store
3. **Run validation**: `python backend/validation/validate_phases.py --summary`
4. **Review report** against success criteria per phase
5. **Iterate**: If regression, investigate; if insufficient events, run more cycles
6. **Flip flags one at a time** once each phase passes
7. **Monitor continuously** post-flip

All code is in:
- Validation framework: `backend/validation/shadow_validator.py`
- CLI tool: `backend/validation/validate_phases.py`
- Tests: `tests/test_shadow_validator.py`
- Event store (existing): `backend/orchestration/event_store.py`
