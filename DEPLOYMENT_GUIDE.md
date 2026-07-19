# Phase 7-8 Production Deployment Guide

**Date**: July 19, 2026  
**Status**: Ready for Staging Validation  
**Branch**: `claude/analyze-repository-fsGUx`

---

## Executive Summary

Complete deployment pipeline for Phase 7-8 (Creative optimization + Organic channel):
- **Staging Validation**: Compare new logic vs baseline
- **Shadow-Mode Rollout**: Parallel tracking on production
- **Organic Expansion**: Affiliate network integrations
- **Production Deployment**: Feature flag gates with validation

All infrastructure tested (26 comprehensive tests), code committed and pushed.

---

## Deployment Architecture

### Four-Layer Pipeline

```
Layer 1: Staging Validator
  ├─ Run scenarios through old vs new paths
  ├─ Compare: rank accuracy, fatigue detection, A/B validity
  └─ Generate recommendation: APPROVE, NEEDS_ITERATION, REJECT

Layer 2: Shadow-Mode Controller
  ├─ Both paths compute decisions on production
  ├─ Old path controls behavior
  └─ New path journaled for validation

Layer 3: Organic Channel Expander
  ├─ Evaluate products for affiliate scaling
  ├─ Fetch affiliate network performance
  └─ Auto-recruit high performers

Layer 4: Feature Flag Manager
  ├─ 6 flags (all default shadow mode)
  ├─ Flip flags when validation gates pass
  └─ Rollback by disabling flag
```

---

## Step-by-Step Deployment

### Step 1: Staging Validation (6-8 hours)

**Goal**: Verify new logic is >= baseline accuracy before production

**Command**:
```bash
# Run staging validator on N scenarios
python -c "
import asyncio
from backend.staging.validator import run_staging_validation

report = asyncio.run(run_staging_validation(num_samples=100))
print(report.summary())
"
```

**What to check**:
- ✅ `rank_accuracy_improvement_pct` > 5% (new logic ranks better)
- ✅ `fatigue_detection_tpr` >= 0.80 (catches declining creatives)
- ✅ `fatigue_detection_fpr` <= 0.10 (no false alarms)
- ✅ `min_samples_gate_compliance` >= 0.95 (A/B gates respected)
- ✅ `urgency_correlation_with_roas` >= 0.65 (urgency predicts well)
- ✅ `recommendation` is "APPROVE" or "NEEDS_ITERATION"

**If all checks pass**: Proceed to Step 2 (Shadow-Mode Rollout)

**If checks fail**: Run NEEDS_ITERATION debug (see "Troubleshooting" below)

---

### Step 2: Shadow-Mode Rollout (30 days)

**Goal**: Run new logic in parallel on production without affecting decisions

**1. Enable shadow-mode flags** (all default enabled):
```bash
# These are already true by default:
export PHASE7_FATIGUE_DETECTION_LIVE_SHADOW=true
export PHASE7_AB_TEST_VALIDITY_LIVE_SHADOW=true
export PHASE7_URGENCY_SCORING_LIVE_SHADOW=true
export PHASE7_MONTE_CARLO_LIVE_SHADOW=true
export PHASE8_ORGANIC_CHANNEL_LIVE_SHADOW=true
export PHASE8_AFFILIATE_SCALING_LIVE_SHADOW=true

# Keep enabled=false (old path controls)
export PHASE7_FATIGUE_DETECTION_LIVE=false
export PHASE7_AB_TEST_VALIDITY_LIVE=false
# ... (all false for shadow mode)
```

**2. Monitor shadow-mode decisions** (30 days):
```bash
# Queries event_store for shadow decisions
from backend.deployment.shadow_mode import shadow_controller

# Check gate status
for flag_name in ["fatigue_detection", "urgency_rank", "organic_channel"]:
    passes, reason = shadow_controller.check_validation_gate(flag_name)
    print(f"{flag_name}: {passes} ({reason})")
```

**3. Validation gates to check** (every 5 days):

| Gate | Target | Current |
|------|--------|---------|
| `fatigue_detection_accuracy` | >= 95% | [run validation] |
| `fatigue_detection_tpr` | >= 80% | [run validation] |
| `ab_test_false_winner_rate` | < baseline | [run validation] |
| `urgency_correlation_roas` | >= 0.65 | [run validation] |
| `organic_cac_mape` | <= 15% | [run validation] |
| `rank_accuracy_new` | >= baseline | [run validation] |

**4. At day 30**: If all gates pass → Proceed to Step 3 (Flip Flags)

**If gates fail**: Revert to baseline, debug, iterate (add to next release)

---

### Step 3: Flip Flags to Production (Rolling, Hour-By-Hour)

**Goal**: Gradually enable new logic, monitoring for regressions

**Staging → Prod flipping strategy** (rolling, 1 flag per hour):

```python
from backend.deployment.feature_flags import flag_manager, FeatureFlag

# Hour 1: Fatigue Detection
flag_manager.flip_flag(FeatureFlag.PHASE7_FATIGUE_DETECTION_LIVE, enabled=True)
# Monitor: hook ROAS unchanged, fatigue flags appear in logs

# Hour 2: A/B Test Validity
flag_manager.flip_flag(FeatureFlag.PHASE7_AB_TEST_VALIDITY_LIVE, enabled=True)
# Monitor: winner selection stricter (n>=20), false winners decline

# Hour 3: Urgency Scoring
flag_manager.flip_flag(FeatureFlag.PHASE7_URGENCY_SCORING_LIVE, enabled=True)
# Monitor: product ranking changes (high velocity, low saturation prioritized)

# Hour 4: Monte Carlo Intervals
flag_manager.flip_flag(FeatureFlag.PHASE7_MONTE_CARLO_LIVE, enabled=True)
# Monitor: pre-launch risk estimates widened/narrowed appropriately

# Hour 5: Organic Channel
flag_manager.flip_flag(FeatureFlag.PHASE8_ORGANIC_CHANNEL_LIVE, enabled=True)
# Monitor: capital allocation weighted 80% paid / 20% organic

# Hour 6: Affiliate Scaling
flag_manager.flip_flag(FeatureFlag.PHASE8_AFFILIATE_SCALING_LIVE, enabled=True)
# Monitor: new affiliate recruitments appear in logs
```

**Monitoring checklist** (after each flag flip):
- [ ] No spike in error logs
- [ ] Decision metrics stable (ROAS not regressing)
- [ ] Creative fatigue flags reasonable (~5-10% of products)
- [ ] Organic ROAS tracking matches baseline
- [ ] Affiliate performance data flowing correctly
- [ ] No webhook/API failures

**If issues found**: Flip flag immediately back to `enabled=false`
```python
flag_manager.flip_flag(FeatureFlag.PHASE7_URGENCY_SCORING_LIVE, enabled=False)
# Reverts to old logic within seconds
```

---

### Step 4: Monitor & Sustain (Week 1+)

**Post-deployment monitoring** (daily):

```bash
# Dashboard metrics to check daily
1. Product ranking accuracy (new vs baseline)
   - Spearman correlation: new_rank vs realized_roas >= baseline
   
2. Fatigue detection signals
   - % products flagged for refresh: expect ~5-10%
   - True positive rate: >= 80%
   
3. A/B test gating
   - % winners with n >= 20: expect >= 95%
   - False winner rate: expect < baseline
   
4. Organic channel
   - Organic ROAS: tracking within expected range
   - Affiliate CAC: comparing favorably to paid CAC
   - Content gap alerts: flagging products without posts
   
5. Risk metrics
   - Max drawdown: should be equal or better than baseline
   - Portfolio concentration: capped by adaptive limits
```

**Weekly reviews** (every Friday):
- Run `StagingValidator` again on new scenario batch
- Compare: new_logic_roas vs baseline_roas by product
- Identify wins and regressions (top 10 of each)
- File optimization cards if new logic underperforms

---

## Rollback Procedures

### Immediate Rollback (< 1 minute)

If catastrophic issue detected (widespread errors, crashes, decision chaos):

```python
from backend.deployment.feature_flags import flag_manager, FeatureFlag

# Disable all Phase 7-8 flags at once
for flag in [
    FeatureFlag.PHASE7_FATIGUE_DETECTION_LIVE,
    FeatureFlag.PHASE7_AB_TEST_VALIDITY_LIVE,
    FeatureFlag.PHASE7_URGENCY_SCORING_LIVE,
    FeatureFlag.PHASE7_MONTE_CARLO_LIVE,
    FeatureFlag.PHASE8_ORGANIC_CHANNEL_LIVE,
    FeatureFlag.PHASE8_AFFILIATE_SCALING_LIVE,
]:
    flag_manager.flip_flag(flag, enabled=False)

print("🔄 All Phase 7-8 logic reverted to baseline")
```

**Result**: System reverts to Phase 6 logic within seconds (no redeployment needed)

### Graceful Rollback (Day-level issues)

If one component underperforms (e.g., fatigue detection has high FPR):

```python
# Keep overall deployment, just disable the problem component
flag_manager.flip_flag(FeatureFlag.PHASE7_FATIGUE_DETECTION_LIVE, enabled=False)

# Investigate root cause, iterate, re-test in staging
# Redeploy that component separately once fixed
```

---

## Troubleshooting

### Issue: Rank Accuracy Unchanged or Slightly Worse

**Symptom**: `rank_accuracy_improvement_pct` <= 0% in staging validation

**Root causes**:
1. Urgency scoring parameters (velocity/saturation weighting) need tuning
2. Trend velocity signals are noisy (need longer rolling windows)
3. Product scoring baseline is already strong (hard to improve)

**Fixes**:
- Increase rolling window from 30d → 60d days for trend detection
- Weight saturation more heavily: `urgency = score * velocity * (1-saturation)^2`
- Calibrate velocity scaling with production historical data
- Iterate in staging with different parameter sets

### Issue: Fatigue Detection False Positives (FPR > 10%)

**Symptom**: Too many healthy creatives flagged as fatigued

**Root causes**:
1. Decline threshold too low (currently 20%)
2. Recent ROAS window includes normal variance
3. Products have seasonal patterns (spike then dip)

**Fixes**:
- Increase threshold: 20% → 30% decline before flag
- Extend recent window: 7d → 14d (capture real trends vs noise)
- Add seasonal adjustment: if product has historical seasonal pattern, adjust threshold
- Require: decline > threshold AND minimum samples in recent window

### Issue: Organic CAC Estimates Wildly Wrong (MAPE > 30%)

**Symptom**: Projected affiliate performance doesn't match actuals

**Root causes**:
1. Mock data in dry-run mode has different characteristics than real
2. Affiliate network performance is platform/category dependent
3. Commission rates different from estimates

**Fixes**:
- Use real affiliate data from impact.com/Refersion APIs (staging API credentials)
- Segment performance by category (electronics vs beauty have different CAC)
- Track realized commissions vs projected, build correction model
- Manual audit of top 3 affiliate networks before scaling

---

## Feature Flag Reference

| Flag | Description | Default | Stage |
|------|-------------|---------|-------|
| PHASE7_FATIGUE_DETECTION_LIVE | Hook/sequence rolling-window fatigue | false | 1h |
| PHASE7_AB_TEST_VALIDITY_LIVE | Min sample size gates (n>=20) | false | 2h |
| PHASE7_URGENCY_SCORING_LIVE | Product ranking by urgency score | false | 3h |
| PHASE7_MONTE_CARLO_LIVE | Confidence intervals for pre-launch | false | 4h |
| PHASE8_ORGANIC_CHANNEL_LIVE | Organic/UGC in capital allocation | false | 5h |
| PHASE8_AFFILIATE_SCALING_LIVE | Auto-recruit from affiliate networks | false | 6h |

**Shadow mode flags** (all `_SHADOW` variants):
- All default `true` (both paths run)
- Disable if shadow mode itself becomes bottleneck (rare)

---

## Deployment Checklist

```
PRE-DEPLOYMENT
☐ Staging validation: all gates pass (rank_accuracy, fatigue_tpr, ab_validity, urgency)
☐ Shadow-mode data: 30 days of parallel decisions collected
☐ Feature flags: all 6 Phase 7-8 flags verified in shadow mode
☐ Monitoring dashboard: deployed and operational
☐ Rollback procedure: tested (flip flags, verify revert works)
☐ Team briefing: ops/eng aware of deployment plan

HOUR 1: FATIGUE DETECTION
☐ Flip PHASE7_FATIGUE_DETECTION_LIVE to enabled
☐ Monitor: hook ROAS, fatigue flag rate, error logs
☐ Verify: no unexpected creative pauses
☐ Decision: proceed to hour 2 or rollback

HOUR 2: A/B TEST VALIDITY
☐ Flip PHASE7_AB_TEST_VALIDITY_LIVE to enabled
☐ Monitor: winner selection strictness, false winner rate
☐ Verify: A/B test winners have n>=20 samples
☐ Decision: proceed to hour 3 or rollback

... (hours 3-6, similar checks for each flag)

WEEK 1: MONITORING
☐ Daily: check rank accuracy, fatigue signals, organic ROAS
☐ Weekly: run staging validator again, identify regressions
☐ Logs: review event_store for anomalies
☐ Metrics: product performance stable or improving

WEEK 2+: SUSTAIN
☐ Optimize parameters based on production data
☐ File tickets for future improvements
☐ Archive shadow-mode data for analysis
☐ Plan Phase 9 (future roadmap)
```

---

## Success Criteria

**Deployment is successful if**:
1. ✅ Rank accuracy (new logic) >= baseline (within 2% noise margin)
2. ✅ Fatigue detection TPR >= 80%, FPR <= 10%
3. ✅ A/B test false winner rate < baseline
4. ✅ Organic channel ROAS tracking expected (20/80 split)
5. ✅ Zero catastrophic outages during flag flips
6. ✅ Rollback tested and working (< 1 minute to revert)
7. ✅ Team confident enough to enable all flags

**If any criterion fails**: Investigate, iterate, retest in staging before re-attempting production

---

## Support & Escalation

**Issues during deployment**:
1. **Metrics confused?** → Staging Validator tutorial (README.md)
2. **Flag isn't flipping?** → Check env vars, verify flag_manager permissions
3. **Regression detected?** → Flip single flag back to `enabled=false`, investigate root cause
4. **Need to adjust gates?** → Update `StagingValidator.validation_gates` dict, re-run staging

**Emergency contacts** (fictional, for reference):
- On-call SRE: [SRE team]
- ML lead: [Engineering]
- Product owner: [Product]

---

## Appendix: Manual Shadow Decision Logging

If needed to manually log shadow decisions (e.g., for testing):

```python
from backend.deployment.shadow_mode import shadow_record_decision, shadow_record_outcome

# Record decision
shadow_id = shadow_record_decision(
    decision_type="urgency_rank",
    baseline_decision="launch_now",
    baseline_score=0.72,
    baseline_confidence=0.6,
    new_decision="launch_soon",
    new_score=0.75,
    new_confidence=0.75,
    product_id="product_xyz",
)

# Later, record outcome
shadow_record_outcome(
    shadow_id=shadow_id,
    realized_roas=0.78,
    realized_drawdown=0.15,
    realized_orders=42,
)
```

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-07-19 | 1.0 | Initial deployment guide for Phase 7-8 |

---

**Ready for deployment to staging!**

Branch: `claude/analyze-repository-fsGUx` | Tests: 1,513+ passing | Docs: Complete

