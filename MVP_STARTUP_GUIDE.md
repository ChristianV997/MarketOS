# MarketOS Dropship MVP — Startup Guide

This guide walks you through running the MVP dropship system to launch real (sandboxed) ad campaigns and track profitability.

---

## Quick Start (Dry-Run Mode)

If you want to test the system without spending real money:

```bash
# 1. Run the dropship cycle (discovers products, validates, launches on mock APIs)
python -m backend.dropship

# 2. View the results
cat state/dropship.json | python -m json.tool

# 3. Check API costs
curl http://localhost:8000/api/dropship/costs/summary

# 4. Check errors
curl http://localhost:8000/api/dropship/errors/summary
```

Expected output:
- 6 discovered products
- 6 validated products
- 2-3 green products (ready for launch)
- 2-3 campaigns launched on TikTok and Meta (dry-run IDs)

---

## Full Setup (Sandboxed Real APIs)

### 1. Set Up API Credentials

Run the interactive setup wizard:

```bash
python -m backend.cli_setup
```

This will prompt you for:
- **Meta Ads**: Access token + Ad Account ID
- **TikTok Ads**: Access token + Advertiser ID
- **Shopify**: Store URL + API credentials

**For Sandboxed Testing (Recommended):**

#### Meta Ads Sandbox
1. Go to https://developers.facebook.com/apps/
2. Create a test app
3. Use the **Test Ad Account** (not real spend)
4. Generate an access token in **Tools > Token Generator**
5. Copy the token and Ad Account ID

#### TikTok Ads Sandbox
1. Go to https://business.tiktok.com/
2. Create a **TikTok For Business** account
3. Request API access in **Settings > API Access**
4. Create a test application with **$0 daily budget**

#### Shopify Sandbox
1. Go to https://www.shopify.com/
2. Create a **development store** (free, no real products)
3. Create a custom app with **product read/write** permissions
4. Copy the API credentials

### 2. Verify Configuration

```bash
python -m backend.cli_setup status
```

Expected output:
```
✓ META: Ready
✓ TIKTOK: Ready
✓ SHOPIFY: Ready

3/3 services ready for production
```

### 3. Start the System

#### Option A: Run One Cycle

```bash
python -m backend.dropship
```

This runs:
1. **Discover**: Finds trending products (via signals)
2. **Validate**: Scores margin, competition, supplier reliability
3. **Create**: Builds product pages in Shopify
4. **Launch**: Creates campaigns on TikTok + Meta

Output saved to `state/dropship.json`:
```json
{
  "status": "ok",
  "discovered": 6,
  "validated": 6,
  "green": 2,
  "launched": 2,
  "launches": [
    {
      "product": "Wireless Earbuds Pro",
      "confidence": 0.9,
      "budget": 36.00,
      "predicted_roas": 2.0,
      "campaigns": [...]
    }
  ]
}
```

#### Option B: Run the Full Orchestrator (Continuous Loop)

```bash
python -m orchestrator.main
```

This runs the complete system loop:
- Every 10 seconds: Ingests signals (trends, competitor activity)
- Every 15 minutes: Runs a dropship cycle (discover → validate → create → launch)
- Every 5 minutes: Fetches campaign metrics (ROAS, spend, clicks)
- Every 60 minutes: Optimizes budgets (scales winners, kills losers)

### 4. Monitor in Real-Time

#### Start the Dashboard

```bash
streamlit run backend/monitoring/streamlit_dashboard.py
```

Then navigate to http://localhost:8501

#### Via API

```bash
# Campaign summary
curl http://localhost:8000/api/dropship/summary

# Profitability
curl http://localhost:8000/api/dropship/profitability

# Cost tracking
curl http://localhost:8000/api/dropship/costs/summary

# Error tracking
curl http://localhost:8000/api/dropship/errors/summary

# Service status
curl http://localhost:8000/api/dropship/status
```

---

## Cost Tracking & Optimization

Every API call is tracked with its cost. View the cost breakdown:

```bash
curl http://localhost:8000/api/dropship/costs/summary?lookback_minutes=60
```

Response:
```json
{
  "total_spend": 0.0245,
  "num_calls": 24,
  "num_successes": 22,
  "num_errors": 2,
  "error_rate": 0.08,
  "by_service": {
    "meta_ads": {"count": 6, "spend": 0.006},
    "shopify": {"count": 8, "spend": 0.008},
    "tiktok_ads": {"count": 10, "spend": 0.0105}
  }
}
```

---

## Error Tracking & Debugging

All errors are logged with context for diagnosis:

```bash
curl http://localhost:8000/api/dropship/errors/summary?lookback_hours=24
```

Response:
```json
{
  "total_errors": 2,
  "by_stage": [
    {"stage": "discovery", "count": 1, "operations": 1}
  ],
  "top_errors": [
    {"error": "ConnectionError", "message": "Max retries exceeded", "count": 1}
  ]
}
```

Get detailed errors:

```bash
curl http://localhost:8000/api/dropship/errors/recent?limit=10
```

---

## Testing Checklist

Run through this to verify the system is working:

- [ ] **Discovery**: Run `python -m backend.dropship` → products discovered ✓
- [ ] **Validation**: Green products found with confidence score ✓
- [ ] **Creation**: Shopify product pages created ✓
- [ ] **Launch**: Campaigns show "live" status ✓
- [ ] **Costs**: API costs tracked in `state/costs.jsonl` ✓
- [ ] **Errors**: Error telemetry working (if any) ✓
- [ ] **Dashboard**: Streamlit dashboard loads and shows data ✓

---

## Troubleshooting

### "No opportunities discovered"
- Check signal sources (Google Trends, Meta Ad Library)
- Run with: `DEBUG=1 python -m backend.dropship`

### "Campaigns show 'error' status"
- Check if TikTok/Meta credentials are valid
- Review: `curl http://localhost:8000/api/dropship/errors/recent`

### "Shopify product creation fails"
- Verify store URL format: `mystore.myshopify.com`
- Check API key has **product write** permission

### High API costs
- Review: `curl http://localhost:8000/api/dropship/costs/by-service`
- Identify expensive operations (e.g., frequent polling)
- Optimize in Phase 2

---

## Next Steps (Phase 2)

1. **Cost Optimization**
   - Cache signals (don't re-query if unchanged)
   - Batch supplier lookups
   - Sample competition analysis

2. **Real-World Validation**
   - Track actual ROAS vs. predictions
   - Calibrate confidence thresholds
   - Adjust budget scaling

3. **Customer MVP**
   - Credential management UI
   - First-product guided flow
   - Profitability dashboard

4. **Performance Tuning**
   - Profile cost per cycle
   - Optimize for margin → revenue
   - Auto-scale based on performance

---

## Files to Know

| File | Purpose |
|------|---------|
| `backend/config.py` | Credential management |
| `backend/cost_tracking.py` | API cost tracking |
| `backend/error_telemetry.py` | Error logging & telemetry |
| `backend/dropship/__init__.py` | Main dropship pipeline |
| `api/dropship_dashboard.py` | REST API endpoints |
| `state/dropship.json` | Latest cycle results |
| `state/costs.jsonl` | Cost event log |
| `state/errors.jsonl` | Error event log |

---

## Support

- **Test failures?** Run: `python -m pytest tests/ -v --tb=short`
- **Want to add more suppliers?** See: `backend/validation/suppliers.py`
- **Want custom creatives?** See: `backend/creation/creative_generator.py`

---

**Ready to launch?** Run `python -m backend.cli_setup` then `python -m backend.dropship`!
