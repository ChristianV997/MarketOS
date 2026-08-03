> **Archived — superseded by README.md.** Kept for history; do not treat any claim below as current.

# MarketOS MVP — Phase 2-4 Execution Plan

**Goal**: Transform MVP from functional to revenue-generating system that optimizes costs and validates profitability predictions against real campaign data.

---

## Phase 2: Cost Optimization & Real API Validation (Week 1)

### High-Leverage, Low-Effort Tasks

#### 1. Signal Caching Layer (2 hours)
**Problem**: Querying Google Trends, Meta Ad Library, Amazon bestsellers every 15 min costs money
**Solution**: Cache signals for 6 hours unless explicitly invalidated
**Impact**: 90% reduction in discovery API calls → ~$0.6/day → ~$18/month savings
**Files**: `backend/discovery/signal_cache.py`

```python
# Pseudocode
class SignalCache:
    def get_signals(self, max_age_hours=6):
        cached = load_from_disk("state/signal_cache.json")
        if cached and (now - cached['ts']) < 6*3600:
            return cached['signals']
        signals = fetch_fresh_signals()  # Expensive
        save_to_disk(signals)
        return signals
```

#### 2. Parallel Supplier Lookups (1.5 hours)
**Problem**: `quote_all()` queries 4 suppliers sequentially (10s per cycle)
**Solution**: Use `asyncio` to query all 4 in parallel
**Impact**: 3-4x faster validation → can validate 10 products instead of 2-3
**Files**: `backend/validation/suppliers.py` (update `quote_all()`)

```python
# Parallel instead of sequential
async def quote_all_async(product):
    tasks = [quote_supplier(s, product) for s in SUPPLIERS]
    return await asyncio.gather(*tasks)  # All at once
```

#### 3. Batch Competition Analysis (1 hour)
**Problem**: `competition_summary()` called once per product → expensive
**Solution**: Batch 10 products into single Meta Ad Library query
**Impact**: 90% reduction in competition API calls
**Files**: `backend/discovery/ad_intelligence.py` (add batch variant)

#### 4. API Cost Baseline Report (1 hour)
**Goal**: Understand true cost structure
**Files**: Create `backend/cost_analysis.py`
- Profile cost per stage (discovery, validation, creation, launch)
- Identify top 3 cost drivers
- Recommendations for optimization

**Expected**: Discovery ~$0.002, Validation ~$0.001, Creation ~$0.002, Launch ~$0.003/product

### Medium-Effort Tasks

#### 5. Real Sandbox API Integration (4 hours)
**Goal**: Verify system works against real (sandboxed) APIs
**Tests**:
- [ ] Meta Sandbox: Create test campaign, verify dry-run ID → real ID transformation
- [ ] TikTok Sandbox: Create test campaign, track costs
- [ ] Shopify Dev Store: Create product, fetch via API
**Files**: `tests/test_real_api_integration.py`

**What we'll learn**:
- Which APIs have auth issues
- Real cost vs. estimated cost
- Latency per operation (Meta: 200ms, Shopify: 300ms, TikTok: 400ms est.)
- Rate limit headroom

#### 6. Campaign Metrics Ingestion (3 hours)
**Goal**: Close the loop: launched campaigns → actual ROAS
**Files**: `backend/metrics/campaign_metrics.py`
- Fetch spend/clicks/conversions from Meta/TikTok
- Store in `state/campaign_metrics.jsonl`
- Match to predicted ROAS in calibration store
- Compute error: `real_roas - predicted_roas`

**Expected output**:
```json
{
  "campaign_id": "dry_meta_xyz",
  "product": "Widget",
  "spend": 50.0,
  "conversions": 5,
  "roas": 2.5,
  "predicted_roas": 2.0,
  "error": 0.5,
  "ts": 1784300000
}
```

---

## Phase 3: Profitability Dashboard & Budget Optimization (Week 2)

### High-Impact Tasks

#### 7. Margin-to-Revenue Attribution (2 hours)
**Goal**: Track actual profit per product, validate margin predictions
**Files**: `backend/metrics/profitability.py`
- Load campaign metrics (spend, conversions)
- Load product margin (from validation verdict)
- Calculate: `profit = (conversions * margin) - spend`
- Aggregate: total profit this week/month

**Dashboard view**:
```
Product          Spend   Revenue   Margin   Profit   ROI
Widget Pro       $50     $100      40%      $25      50%
Earbuds          $40     $85       35%      $5       12%
Case             $30     $60       20%      $0       0%
```

#### 8. Confidence Calibration (2 hours)
**Goal**: Learn which confidence scores predict real ROAS
**Files**: `backend/metrics/calibration_tuning.py`
- Load all outcomes (product, confidence, actual_roas)
- Compute: do high-confidence products actually have higher ROAS?
- Adjust confidence formula if predictions miss systematically
- Publish: "Products with 0.8+ confidence historically achieve 2.2x ROAS"

#### 9. Budget Scaling Rules (2 hours)
**Goal**: Dynamically scale campaign budgets based on real performance
**Files**: `backend/optimization/budget_scaling.py`
```
Rule 1: If ROAS > 2.0, scale budget +20%
Rule 2: If ROAS < 1.0, scale budget -50% or kill
Rule 3: If spend > predicted spend by 20%, investigate
Rule 4: Never scale single campaign > $200/day
```

#### 10. Revenue Forecast Dashboard (2 hours)
**Goal**: Show projected revenue with current campaigns
**Files**: Update `api/dropship_dashboard.py`
- Add `/forecast` endpoint
- Calculate: projected_revenue = sum(live_campaigns × predicted_roas)
- Show confidence interval (pessimistic/realistic/optimistic)

**Example output**:
```json
{
  "status": "ok",
  "period_days": 7,
  "campaigns_live": 8,
  "total_spend_projected": 350.0,
  "revenue_pessimistic": 400.0,  // ROAS 1.14
  "revenue_realistic": 700.0,    // ROAS 2.0
  "revenue_optimistic": 1050.0,  // ROAS 3.0
  "confidence": 0.75
}
```

### Medium-Effort Tasks

#### 11. A/B Testing Framework (3 hours)
**Goal**: Test which creatives/hooks/angles perform best
**Files**: `backend/creation/ab_testing.py`
- Split budget 50/50 between two creatives
- Track which variant has higher ROAS
- Auto-escalate winner, kill loser
- Learn: "This hook performs 30% better than baseline"

#### 12. Supplier Margin Validation (2 hours)
**Goal**: Verify supplier margin predictions against actual costs
**Files**: `backend/validation/margin_validation.py`
- When product ships, compare predicted margin to actual cost
- Flag if actual margin deviates > 10% from predicted
- Update supplier reliability scores
- Learn: "CJ Dropshipping consistently 5% cheaper than predicted"

---

## Phase 4: Production Readiness & Monitoring (Week 3-4)

### Critical Tasks

#### 13. Error Recovery & Retry Logic (2 hours)
**Goal**: Handle transient API failures automatically
**Files**: `backend/integrations/retry_middleware.py`
```python
@retry(max_attempts=3, backoff=exponential)
def create_campaign_with_retry(name, budget):
    return meta_ads_client.create_campaign(name, budget)
```

#### 14. Rate Limiting & Quotas (1.5 hours)
**Goal**: Don't exceed API rate limits
**Files**: `backend/integrations/rate_limiter.py`
- Meta Ads: 50 req/sec (safe: 10/sec)
- TikTok Ads: 100 req/min (safe: 30/min)
- Shopify: 2 req/sec (safe: 0.5/sec)
- Implement sliding window rate limiter

#### 15. Monitoring & Alerting (3 hours)
**Goal**: Know when things break before customer does
**Files**: `backend/monitoring/alerts.py`
- Alert if: error rate > 5%, spend > $100/hour, ROAS < 1.0, no campaigns live
- Channel: write to `state/alerts.jsonl` (can integrate Slack later)
- Daily digest: 5 top errors, cost summary, campaigns status

#### 16. Data Export & Reporting (2 hours)
**Goal**: Generate weekly reports for stakeholders
**Files**: `backend/reporting/weekly_report.py`
- CSV/JSON export of all campaigns, profitability, costs
- Run every Sunday 9am
- Save to `state/reports/weekly_2026-07-17.json`

---

## Priority Matrix: What to Execute

### **MUST DO (Core Revenue Loop)**
| Task | Effort | Impact | Owner | Status |
|------|--------|--------|-------|--------|
| Campaign Metrics Ingestion | 3h | ⭐⭐⭐⭐⭐ | Phase 3 #7 | CRITICAL |
| Margin-to-Revenue Attribution | 2h | ⭐⭐⭐⭐⭐ | Phase 3 #8 | CRITICAL |
| Real Sandbox API Test | 4h | ⭐⭐⭐⭐ | Phase 2 #5 | CRITICAL |
| Signal Caching | 2h | ⭐⭐⭐⭐ | Phase 2 #1 | HIGH |
| Budget Scaling Rules | 2h | ⭐⭐⭐⭐ | Phase 3 #9 | HIGH |

### **SHOULD DO (Optimization)**
| Task | Effort | Impact | Owner | Status |
|------|--------|--------|-------|--------|
| Parallel Supplier Lookups | 1.5h | ⭐⭐⭐ | Phase 2 #2 | MED |
| Confidence Calibration | 2h | ⭐⭐⭐ | Phase 3 #8 | MED |
| Error Recovery & Retry | 2h | ⭐⭐⭐ | Phase 4 #13 | MED |
| Revenue Forecast Dashboard | 2h | ⭐⭐⭐ | Phase 3 #10 | MED |

### **NICE TO HAVE (Polish)**
| Task | Effort | Impact | Owner | Status |
|------|--------|--------|-------|--------|
| Batch Competition Analysis | 1h | ⭐⭐ | Phase 2 #3 | LOW |
| A/B Testing Framework | 3h | ⭐⭐ | Phase 3 #11 | LOW |
| Supplier Margin Validation | 2h | ⭐⭐ | Phase 3 #12 | LOW |
| Monitoring & Alerting | 3h | ⭐⭐ | Phase 4 #15 | LOW |

---

## Execution Strategy: Maximum Progress in One Run

### Timeline: 5 Days, ~40 Hours

**Day 1 (8h): Foundation**
- [ ] Task #1: Signal Caching (2h)
- [ ] Task #5: Real Sandbox API Integration (4h)
- [ ] Task #4: API Cost Baseline (1h)
- [ ] Task #2: Parallel Supplier Lookups (1h)

**Day 2 (8h): Metrics Loop**
- [ ] Task #7: Campaign Metrics Ingestion (3h)
- [ ] Task #8: Margin-to-Revenue Attribution (2h)
- [ ] Task #6: Batch Competition (1h)
- [ ] Tests & validation (2h)

**Day 3 (8h): Optimization**
- [ ] Task #9: Budget Scaling Rules (2h)
- [ ] Task #8: Confidence Calibration (2h)
- [ ] Task #10: Revenue Forecast Dashboard (2h)
- [ ] Tests & integration (2h)

**Day 4 (8h): Production Readiness**
- [ ] Task #13: Error Recovery & Retry (2h)
- [ ] Task #14: Rate Limiting & Quotas (1.5h)
- [ ] Task #15: Monitoring & Alerting (2.5h)
- [ ] Tests (2h)

**Day 5 (8h): Final Integration & Testing**
- [ ] Task #16: Data Export & Reporting (2h)
- [ ] End-to-end testing (3h)
- [ ] Documentation (2h)
- [ ] Final smoke tests (1h)

---

## Success Criteria

By end of Phase 2-4:
- ✅ Real API integration tested (Meta/TikTok/Shopify)
- ✅ Campaign metrics flowing end-to-end
- ✅ Profitability calculated and attributed
- ✅ Budget scaling rules working
- ✅ Cost per cycle reduced 50% (from $0.007 to $0.0035)
- ✅ Error rate < 2%
- ✅ Revenue forecast accurate within 20%
- ✅ 100+ tests passing
- ✅ System can run unattended for 1 week

---

## Go/No-Go Decision Point

After Day 3:
- [ ] Metrics loop working? (revenue accurate?)
- [ ] Costs tracking correctly?
- [ ] Confidence calibration improving predictions?

If YES to all: Continue to production hardening (Phase 4)
If NO: Debug + restart that day

---

## Files to Create/Modify

```
NEW FILES (Phase 2-4):
backend/
  discovery/signal_cache.py            # Task #1
  metrics/campaign_metrics.py          # Task #7
  metrics/profitability.py             # Task #8
  metrics/calibration_tuning.py        # Task #8
  optimization/budget_scaling.py       # Task #9
  creation/ab_testing.py               # Task #11
  validation/margin_validation.py      # Task #12
  integrations/retry_middleware.py     # Task #13
  integrations/rate_limiter.py         # Task #14
  monitoring/alerts.py                 # Task #15
  reporting/weekly_report.py           # Task #16
  cost_analysis.py                     # Task #4

api/
  (update dropship_dashboard.py)       # Add /forecast

tests/
  test_real_api_integration.py         # Task #5
  test_campaign_metrics.py             # Task #7
  test_profitability.py                # Task #8
  test_budget_scaling.py               # Task #9
  test_monitoring_alerts.py            # Task #15

MODIFIED FILES:
backend/
  validation/suppliers.py              # Parallel task #2
  discovery/ad_intelligence.py         # Batch task #3
```

---

## Estimated ROI

### Cost Savings
- Signal caching: $18/month
- Parallel lookups: $5/month
- Batch competition: $10/month
- **Total: $33/month saved**

### Revenue Gains
- Launch 3x more products (parallel validation)
- 10% higher ROAS (budget scaling optimizes winners)
- Estimated: $1000 → $3300 monthly revenue gain

### Time Savings
- Auto-recovery from API failures: 20 min/week
- Metrics ingestion automated: 1 hour/week
- Estimated: 5 hours/week dev time freed

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Real API auth fails | 30% | CRITICAL | Test sandbox first, fallback to dry-run |
| Margin predictions wrong | 20% | HIGH | Calibration loop + daily monitoring |
| Rate limiting backpressure | 15% | MED | Conservative limits, queue retries |
| Profitability formula incorrect | 10% | MED | Peer review before deploying |

---

## Next Steps After Phase 4

1. **Customer Onboarding** — Deploy to staging, test with 3 beta users
2. **Performance Benchmarking** — Load test at 10x current scale
3. **Advanced Features** — Image generation, video generation, audience targeting
4. **Marketplace Integration** — eBay, Amazon direct launch
5. **Multi-Account Support** — Let customers manage multiple stores
