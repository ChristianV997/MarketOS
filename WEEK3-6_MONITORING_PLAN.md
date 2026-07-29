# Week 3-6 Continuous Monitoring & Monthly Validation Plan

**Status**: Week 2 Stage 2 Complete  
**Phases Live**: 6/8 (Phase 2, 4, 5, 6 fully live; Phases 3, 6 supplementary tuning applied)  
**Next Review**: Monthly validation runs  
**Goal**: Maintain production stability, collect data for Week 7+ Phases 7-8 decision

---

## Monthly Validation Schedule

### Deployment: Add to Production Cron

```bash
# Add to /etc/cron.d/marketos or crontab
0 0 1 * * cd /home/user/my_OS && python backend/validation/shadow_validator_v2.py >> /var/log/marketos_validation.log 2>&1
0 1 1 * * cd /home/user/my_OS && python backend/validation/validate_phases.py --summary >> /var/log/marketos_validation.log 2>&1
```

### Manual Monthly Validation (recommended first run)

```bash
# Export current production flags
export CAPITAL_POLICY_LIVE=true
export REGIME_DETECTION_LIVE=true
export RISK_ADAPTIVE_LIVE=true
export ECONOMICS_GEO_LIVE=true

# Run validation
python backend/validation/shadow_validator_v2.py --output validation_$(date +%Y%m%d).json

# Compare to baseline
jq '.capital_policy.metrics' validation_20250801.json
jq '.regime_detection.metrics' validation_20250801.json
```

---

## Critical Metrics Dashboard

Track these metrics per phase every 24 hours:

| Phase | Metric | Alert If | Baseline | Target |
|-------|--------|----------|----------|--------|
| **2: Capital** | allocations_valid_pct | < 99% | 100% | ≥ 99% |
| **2: Capital** | budget_respected_pct | < 99% | 100% | ≥ 99% |
| **4: Regime** | changepoint_detection_rate | < 1% or > 15% | 2.5% | 1-15% |
| **4: Calib** | valid_holdout_split_pct | < 95% | 98% | ≥ 95% |
| **5: Risk** | adaptive_more_permissive_pct | < 99% | 100% | ≥ 99% |
| **6: Geo** | margin_adjusted_lte_raw_pct | < 99% | 100% | ≥ 99% |
| **6: Regime Conf** | bonus_adjusted_lte_raw_pct | < 99% | 100% | ≥ 99% |

### System-Level Metrics

| Metric | Alert If | Tool |
|--------|----------|------|
| Capital total | < Initial - 20% | Python loop tracking |
| Risk cap violations | > 0 | backend/risk/config.py logs |
| Supplier changes | (tuning monitor) | backend/validation/suppliers.py events |
| Decision norm in-range | < 97% | Phase 3 shadow events |

---

## Week-by-Week Checklist

### Week 3 (Days 15-21)
- [ ] Day 15: Validate all 6 phases still passing after 5 days live
- [ ] Day 17: Check capital tracking (should be positive/stable)
- [ ] Day 19: Review regime detection events (should see 2-3% changepoint rate)
- [ ] Day 21: First weekly report

**Success Criteria**: All 6 phases maintain validation passes

### Week 4 (Days 22-28)
- [ ] Day 22: Run 100 more decision cycles
- [ ] Day 24: Re-validate
- [ ] Day 26: Check for any pattern anomalies
- [ ] Day 28: Second weekly report

**Success Criteria**: No regressions, metrics stable

### Week 5 (Days 29-35)
- [ ] Day 29: Run 100 more decision cycles
- [ ] Day 1 (May): **MONTHLY VALIDATION RUN** (cron should execute)
- [ ] Review monthly trends
- [ ] Days 31-35: Final prep for graduation decision

**Success Criteria**: Monthly validation shows sustained improvement

### Week 6 (Days 36-42)
- [ ] Days 36-41: Continue monitoring
- [ ] Day 42: **DECISION POINT: Graduate to Full Live?**
  - If all 6 phases passing: **YES** → Week 7 can activate Phases 7-8
  - If any regression: **NO** → Debug, stabilize, extend monitoring

**Success Criteria**: Ready to graduate or identified issues for fix

---

## Alert Thresholds & Response

### 🔴 CRITICAL (Immediate Action Required)

**Condition**: Any phase fails validation (status: "fail")  
**Response**: 
1. Immediately disable that phase: `export [PHASE_FLAG]=false`
2. Restart system: `systemctl restart marketOS`
3. Investigate root cause in event_store
4. Fix and re-validate before re-enabling

**Condition**: Capital goes negative  
**Response**:
1. This shouldn't happen if Phase 5 (adaptive risk) is working
2. Check if risk caps are being violated
3. Review latest 20 decision cycles for anomalies
4. If issue persists, disable Phase 2 (capital policy) and revert to legacy

### 🟡 WARNING (Review Within 24hrs)

**Condition**: Phase metric outside baseline range  
**Response**:
1. Review event data for that phase
2. Check if it's a test data artifact or production issue
3. Note trend (improving or degrading)
4. Plan fix if trend is degrading

**Condition**: Supplier change rate < 5% or > 40%  
**Response**:
1. If < 5%: Risk adjustment may not be differentiating enough (tuning issue)
2. If > 40%: Risk adjustment may be too aggressive (instability)
3. Review supplier feedback events
4. Adjust RETURN_RELIABILITY_SENSITIVITY if needed

### 🟢 NOMINAL (Routine Monitoring)

All phases passing, metrics in baseline range, capital stable/positive.

---

## Monitoring Tools & Commands

### Real-Time Validation

```bash
# Check current state
python backend/validation/shadow_validator_v2.py --summary

# Export detailed JSON for analysis
python backend/validation/shadow_validator_v2.py --output latest_validation.json

# Check specific phase
python backend/validation/shadow_validator_v2.py --phase capital_policy
```

### Event Store Analysis

```bash
# Count events by type
python3 << 'EOF'
import json
events = {}
with open('state/workflow_executions.jsonl') as f:
    for line in f:
        event = json.loads(line)
        et = event['event']
        events[et] = events.get(et, 0) + 1
for et, count in sorted(events.items(), key=lambda x: -x[1])[:15]:
    print(f"{et:40} {count:6d}")
EOF

# Inspect specific events
jq '[.[] | select(.event == "shadow_capital_policy") | .data] | .[0:3]' state/workflow_executions.jsonl
```

### Capital Tracking

```bash
# Quick snapshot
python -c "
from backend.core.state import SystemState
state = SystemState()
print(f'Current capital: \${state.capital:,.0f}')
print(f'Transition cooldown: {state.transition_cooldown}')
print(f'Detected regime: {state.detected_regime}')
"
```

---

## Contingency Plans

### If Phase Fails Validation

**Phase 2 (Capital Allocation)**:
```bash
export CAPITAL_POLICY_LIVE=false
# Revert to legacy budget_allocator (LP without mean-variance)
```

**Phase 4 (Regime Detection)**:
```bash
export REGIME_DETECTION_LIVE=false
# Revert to hardcoded regime (stays at last detected)
```

**Phase 5 (Adaptive Risk)**:
```bash
export RISK_ADAPTIVE_LIVE=false
# Revert to static risk caps (max_drawdown=0.30, daily_spend=$10k)
```

**Phase 6 (Geo Economics)**:
```bash
export ECONOMICS_GEO_LIVE=false
# Revert to flat-rate margin calculation (no geo adjustment)
```

### If Multiple Phases Fail

Disable all production flags and revert to shadow mode:
```bash
export CAPITAL_POLICY_LIVE=false
export REGIME_DETECTION_LIVE=false
export RISK_ADAPTIVE_LIVE=false
export ECONOMICS_GEO_LIVE=false
systemctl restart marketOS
```

---

## Preparation for Week 7+

### Prerequisites to Flip Phases 7-8

Before enabling Phase 7 (Creative Fatigue) and Phase 8 (Organic Channel):

1. **All 6 phases maintain passing validation** for 4 consecutive weeks
2. **No regressions** vs. original baseline metrics
3. **Capital stability** (positive, not trending down)
4. **Feedback loops operational**:
   - Supplier feedback EMA decaying properly
   - Regime changes detected within 2 days
   - Risk caps preventing over-leverage

### Phase 7 Shadow Data Preparation

Phases 7 (Creative Fatigue) and 8 (Organic Channel) have already been wired for shadow-mode logging:
- `shadow_creative_fatigue` events being collected during cycles
- `shadow_organic_channel` events being collected during cycles

By end of Week 6, we'll have:
- 4+ weeks of Phase 7-8 shadow data
- 100+ creative fatigue events (for trend detection validation)
- 50+ organic channel events (for CAC efficiency validation)

### Decision Criteria (Day 42)

**Graduate 6 phases to "Full Live"** if:
- ✅ All 6 phases pass monthly validation (4 consecutive times)
- ✅ Sharpe ratio improved ≥ 3% vs. baseline
- ✅ Cost per order improved ≥ 5% (geo-adjusted)
- ✅ Drawdown incidents ≤ 25% of historical rate
- ✅ Support tickets unchanged or decreased
- ✅ No data quality issues in event_store

**Then activate Phases 7-8** if:
- ✅ Creative fatigue detection latency ≤ 3 days
- ✅ Organic channel trial successful (5 creators, CAC < 60% of paid)
- ✅ Shadow validation shows both phases performing well

---

## Success Criteria (End of Week 6)

### Minimum Viable
- All 6 phases remain live and passing validation
- No critical incidents requiring rollback
- Capital tracking accurate and stable
- System ready to activate Phases 7-8

### Target
- Sharpe ratio improved 3-5%
- Cost per order reduced 5-10%
- Drawdown incidents down 25%+
- All phases exceed baseline performance

### Exceptional
- ROI uplift measurable and significant
- All 8 phases performing at target levels
- System ready for full optimization

---

## Handoff Notes

This monitoring plan is designed to be:
1. **Autonomous**: Monthly cron jobs run without intervention
2. **Transparent**: All metrics logged and queryable
3. **Safe**: Multiple layers of alerting before critical action
4. **Scalable**: Can be extended to include additional phases or metrics

By end of Week 6, this system will have generated 400+ decision cycles of production data, sufficient to make the Week 7+ decision with high confidence.

---

**Created**: Week 2 Stage 2 Complete  
**Effective**: Immediately  
**Next Review**: July 1, 2025 (First Monthly Validation)
