> **Archived — superseded by README.md.** Kept for history; do not treat any claim below as current.

# MarketOS Performance & Cost Optimization Guide

This guide identifies the hottest code paths and provides specific optimization strategies for the MVP.

## 🔴 Critical Path Optimizations

### 1. Product Discovery (Signal Fetching) - HIGHEST IMPACT
**Current**: 6-hour cache, parallel sourcing
**Cost**: ~$0.01 per discovery call (multiple vendor APIs)
**Frequency**: Every dropship cycle (~5-10 min in production)

**Optimization Strategy**:
- ✅ Already cached with 6h TTL (implemented)
- ✅ Parallel sourcing in `get_signals_cached()` (implemented)
- **TODO**: Batch category lookups (group 10 categories per call)
- **TODO**: Add category trending heuristics to pre-warm cache
- **TODO**: Implement LRU cache for recent searches (avoid duplicate cache hits)

**Estimated Savings**: 40-60% reduction in discovery API calls

### 2. Supplier Validation (Quotes) - HIGH IMPACT
**Current**: ThreadPoolExecutor parallel, 4 suppliers
**Cost**: $0.05-$0.15 per validation (supplier API fees + data costs)
**Frequency**: Every validation cycle (~15-30 sec per product)

**Optimization Strategy**:
- ✅ Already parallelized with ThreadPoolExecutor (implemented)
- **TODO**: Cache supplier data for 24h (prices don't change much daily)
- **TODO**: Skip low-margin suppliers early (filter before quoting)
- **TODO**: Batch quote requests per supplier (5-10 products per call)
- **TODO**: Implement circuit breaker (skip supplier if >2 consecutive failures)

**Estimated Savings**: 50-70% reduction in supplier validation costs

### 3. Campaign Metrics Aggregation - MEDIUM IMPACT  
**Current**: Per-campaign aggregation, JSONL event log
**Cost**: Minimal ($0), but IO-heavy
**Frequency**: Every metrics observation (~5-10 min)

**Optimization Strategy**:
- ✅ Appends to JSONL (no re-reads)
- **TODO**: Implement rolling 7-day window (archive old metrics)
- **TODO**: Pre-aggregate by platform (Meta, TikTok separate)
- **TODO**: Cache aggregation results for 1h (most queries within window)

**Estimated Savings**: 30-40% reduction in metrics processing time

### 4. Profitability Calculation - MEDIUM IMPACT
**Current**: Full join of launches + metrics every call
**Cost**: Minimal, but CPU-intensive
**Frequency**: Every scaling decision (~1-2 min)

**Optimization Strategy**:
- **TODO**: Cache calculated profitability for 10 min (unless new metrics arrive)
- **TODO**: Lazy-load product margin (only for top 10 by spend)
- **TODO**: Vectorize calculations with NumPy for bulk operations
- **TODO**: Pre-filter unprofitable products (margin < threshold) early

**Estimated Savings**: 60-70% reduction in profitability calc time

### 5. Campaign Launch Orchestration - MEDIUM IMPACT
**Current**: Sequential create campaign → create adset → create ad
**Cost**: $0.003-$0.005 per campaign (Meta/TikTok API)
**Frequency**: Every launch cycle (~1 per dropship)

**Optimization Strategy**:
- ✅ Rate limiting implemented (prevent quota exhaustion)
- **TODO**: Batch create adsets for same campaign (Meta supports)
- **TODO**: Template pre-made creatives (avoid re-generating)
- **TODO**: Reuse paused campaigns if same product (no cost, just resume)

**Estimated Savings**: 20-30% reduction in launch costs

## 📊 Quick Wins (Low Effort, High ROI)

### 1. Add Supplier Circuit Breaker (2 hours)
```python
# After 3 consecutive failures, skip supplier for 1h
# Saves time + prevents cascading timeouts
```
**Impact**: Prevent long tail failures from blocking all validation

### 2. Implement Simple Result Caching (1 hour)
```python
# Cache discovery results for 6h
# Cache supplier quotes for 24h  
# Cache profitability for 10 min
```
**Impact**: 40-50% reduction in API calls

### 3. Add Cost Tracking Per Operation (1 hour)
```python
# Track actual spend: discovery $0.01/call, validation $0.10/product
# Aggregate by operation type and date
# Report in weekly summary
```
**Impact**: Understand real economics per customer

### 4. Lazy-Load Product Details (2 hours)
```python
# Only fetch detailed product info when needed
# Skip full descriptions for filtering/scoring
# Load details only for top products after ranking
```
**Impact**: 30-40% faster discovery phase

## 🎯 Measurement & Validation

### Setup Performance Baseline
```bash
# Run profiler for each component
python scripts/profile_hotspots.py discovery
python scripts/profile_hotspots.py validation
python scripts/profile_hotspots.py metrics
python scripts/profile_hotspots.py profitability
python scripts/profile_hotspots.py dropship
```

### Track Improvements
1. **Latency**: Time per operation (discovery, validation, launch)
2. **Cost**: Actual API spend per customer per day
3. **Cache Hit Rate**: % of cache hits in discovery/validation
4. **Error Rate**: % of operations that fail/timeout

### Success Criteria for MVP
- [ ] Discovery cycle: <5 seconds (was ~10s)
- [ ] Validation cycle: <15 seconds per product (was ~30s)
- [ ] Full dropship cycle: <2 minutes (was ~5 min)
- [ ] Cost per customer per day: <$0.50 in APIs (excluding ads)
- [ ] Cache hit rate: >70% for discovery
- [ ] Error rate: <1% of operations

## 🚀 Phase-Based Optimization Plan

### Phase 1: Pre-Launch (Next 1 week)
- [ ] Add result caching (discovery + supplier quotes)
- [ ] Implement cost tracking per operation
- [ ] Add circuit breaker for supplier failures
- [ ] Run full performance baseline

### Phase 2: Customer MVP (Week 2-3)
- [ ] Lazy-load product details
- [ ] Batch supplier quotes per provider
- [ ] Pre-aggregate metrics for dashboard
- [ ] Cache profitability calculations

### Phase 3: Production Optimization (Post-Launch)
- [ ] Monitor real-world latencies and costs
- [ ] Fine-tune cache TTLs based on hit rates
- [ ] Implement smart scheduling (off-peak operations)
- [ ] Add auto-scaling for high-volume customers

## 💡 Code Locations for Each Optimization

| Optimization | File | Function | Effort |
|--------------|------|----------|--------|
| Discovery caching | `backend/discovery/signal_cache.py` | `get_signals_cached` | ✅ Done |
| Supplier caching | `backend/validation/suppliers.py` | `quote_all` | 1h |
| Circuit breaker | New file | `SupplierCircuitBreaker` | 2h |
| Metrics cache | `backend/metrics/campaign_metrics.py` | `campaign_performance` | 1h |
| Profitability cache | `backend/metrics/profitability.py` | `calculate_profitability` | 1h |
| Cost tracking | `backend/cost_tracking.py` | Extend existing | 1h |
| Lazy loading | `backend/discovery/__init__.py` | `discover_products` | 2h |
| Launch batching | `backend/integrations/meta_ads_client.py` | `create_ad_set` | 1h |

## 🔍 Profiling Commands

```bash
# Profile entire dropship cycle
python scripts/profile_hotspots.py dropship

# Profile individual components
python scripts/profile_hotspots.py discovery
python scripts/profile_hotspots.py validation  
python scripts/profile_hotspots.py metrics
python scripts/profile_hotspots.py profitability

# Run tests with coverage
pytest tests/ --cov=backend --cov-report=html

# Check for bottlenecks in specific module
python -m cProfile -s cumulative -m pytest tests/test_backend.py
```

## ✅ Monitoring Checklist

- [ ] Add logging timestamps to all major operations
- [ ] Track API call counts per service per day
- [ ] Monitor cache hit/miss rates
- [ ] Alert on operation timeouts (>30s)
- [ ] Track error rates by operation type
- [ ] Measure end-to-end cycle time daily
- [ ] Review cost per customer weekly

This guide should be updated as optimizations are implemented and measurements are collected.
