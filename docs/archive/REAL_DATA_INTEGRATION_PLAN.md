# MarketOS Real Data Integration Plan

**Phase**: Post-Production Data Wiring  
**Objective**: Replace synthetic test data with real market datasets  
**Scope**: Product discovery, market validation, competitor/influencer analysis  
**Timeline**: 4-6 weeks (parallel with Week 3-6 production monitoring)  
**Complexity**: High (requires external API integrations, schema migration)

---

## Current State Assessment

### What's Running on Synthetic Data (Mock)
```
1. ROAS Generation
   - Random 0.5-3.0 per cycle (backend/execution/loop.py::_generate_roas)
   - No real ad platform data
   - No platform-specific dynamics (Meta vs TikTok learning curves)
   - No seasonal patterns

2. Products & Variants
   - Synthetic IDs: "product_1" through "product_N"
   - Mock creative hooks/angles
   - Fake supplier costs, shipping
   - No real SKU inventory

3. Market Signals
   - Reddit trends: Hardcoded mock signals
   - YouTube trends: Fake view counts
   - Google Trends: Zero real data
   - Ad intelligence: Mocked competitor data

4. Customer Attribution
   - Synthetic customer IDs
   - Mock order data
   - Fake multi-touch attribution
   - No real Shopify orders

5. Supplier Reliability
   - Static mock reliability scores
   - No real stockout/delay history
   - No actual supplier complaints
   - Hardcoded shipping times

6. Financial Metrics
   - Fake revenue derived from random ROAS
   - Mock customer CAC
   - Synthetic repeat purchase rates
   - No real profit margins
```

### Where Real Data Should Flow
```
├── Product Discovery
│   ├── Successful products (Shopify sales data)
│   ├── Rising trends (Reddit, Twitter, TikTok)
│   ├── Google Trends validation
│   ├── Competitor products (AliExpress, Amazon)
│   └── Supplier catalogs (CJ, Spocket, Printful)
│
├── Market Validation
│   ├── Real ROAS by product/platform
│   ├── Customer CAC by geo/audience
│   ├── Conversion rates by product category
│   ├── Return/refund rates
│   └── Customer LTV cohort data
│
├── Publicity Strategies
│   ├── Successful TikTok/Instagram campaigns
│   ├── Influencer/UGC content performance
│   ├── Creative hooks that work (by category)
│   ├── Audience segments by engagement
│   └── Seasonal/trend-driven success patterns
│
└── Operational Metrics
    ├── Supplier reliability (actual stockouts)
    ├── Shipping performance (real delays)
    ├── Payment method success rates
    └── Regional market dynamics
```

---

## Phase 0: Credential & Access Audit

### Required (User Must Provide or Authorize)

**Shopify**:
- [ ] Store URL(s)
- [ ] Admin API access token (read: products, orders, customers)
- [ ] Scope: read_products, read_orders, read_customers, read_fulfillments
- [ ] Data volume: All products, 12+ months order history
- [ ] Frequency: Real-time (webhook) + daily batch

**Meta (Facebook) Ads**:
- [ ] Business Account ID
- [ ] Ad Account ID(s)
- [ ] App ID + App Secret (for graph API)
- [ ] Scope: campaigns, insights (ROAS, CPC, CTR)
- [ ] Data: All campaigns, last 12 months
- [ ] Frequency: Daily (Meta aggregates 24hr behind)

**TikTok Ads**:
- [ ] Business Account ID
- [ ] API access (OAuth or PAT)
- [ ] Advertiser ID(s)
- [ ] Scope: campaign metrics, creative performance
- [ ] Data: Campaign-level ROAS, engagement
- [ ] Frequency: Daily

**Google Trends**:
- [ ] API key (Trends API v2, requires signup)
- [ ] No auth needed (public API)
- [ ] Rate limit: 5 requests/second
- [ ] Frequency: Daily (trends update daily)

**Reddit API**:
- [ ] Client ID + Client Secret (OAuth)
- [ ] User Agent string
- [ ] Scope: Read r/entrepreneur, r/Ecommerce, r/dropshipping (public subreddits)
- [ ] Frequency: Daily (poll trending posts)

**Instagram/TikTok Influencer Data**:
- [ ] API access (Creator Marketplace APIs if available)
- [ ] OR: Third-party influencer databases (HypeAuditor, AspireIQ)
- [ ] Data: Top creators by niche, engagement rates, typical CPM
- [ ] Frequency: Weekly

**Supplier APIs** (Already integrated):
- [ ] CJ Dropshipping API (if credentials exist)
- [ ] Spocket API
- [ ] Printful API
- [ ] AliExpress feeds (unofficial or affiliate data)
- [ ] Data: Product catalog, prices, lead times, reliability scores
- [ ] Frequency: Daily

**Optional** (High-Value if Available):
- [ ] Klaviyo (email/retention data)
- [ ] Stripe (payment methods, chargeback rates)
- [ ] Gorgias/Zendesk (customer complaints, return patterns)
- [ ] Segment (unified customer data)

---

## Phase 1: Data Architecture & Schema (Weeks 1-2)

### 1.1 Real ROAS Dataset

**Current Schema** (Synthetic):
```python
# backend/metrics/profitability.py (mock)
def calculate_profitability(campaign_id, platform):
    return random.uniform(0.5, 3.0)  # Fake ROAS
```

**New Schema** (Real):
```python
# backend/data/roas_repository.py (NEW)
@dataclass
class RoasDataPoint:
    date: datetime
    product_id: str
    platform: str  # "meta" | "tiktok" | "google" | "organic"
    campaign_id: str
    ad_account_id: str
    
    # Actuals from platform
    spend: float  # USD
    revenue: float  # USD (after dedup)
    clicks: int
    impressions: int
    conversions: int
    
    # Derived
    roas: float  # revenue / spend
    cpc: float  # spend / clicks
    ctr: float  # clicks / impressions
    conversion_rate: float  # conversions / clicks
    
    # Meta
    platform_reported_roas: float  # Raw platform value (before dedup)
    attribution_model: str  # "last_click" | "first_click" | "linear"
    confidence: float  # 0.0-1.0 (higher if multi-day aggregation)

class RoasRepository:
    def get_product_roas(self, product_id: str, days: int = 30) -> list[RoasDataPoint]:
        """Fetch real ROAS history for a product (last N days)"""
    
    def get_platform_roas(self, platform: str, days: int = 30) -> list[RoasDataPoint]:
        """Compare platform performance (Meta vs TikTok)"""
    
    def get_campaign_roas(self, campaign_id: str) -> RoasDataPoint:
        """Single campaign snapshot"""
    
    def deduplicate_cross_platform(self, orders: list[Order]) -> list[RoasDataPoint]:
        """Reconcile multi-touch attribution (Phase 1 logic)"""
```

**Data Ingestion**:
```python
# backend/connectors/meta_ads_client.py (MODIFY for real data)
class MetaAdsConnector:
    async def fetch_daily_insights(self, date: datetime) -> list[RoasDataPoint]:
        """
        Call Graph API: /me/adsets?fields=insights.date_start(DATE).date_stop(DATE)
        Returns: spend, impressions, clicks, actions[PURCHASE], action_values[PURCHASE]
        """
    
    async def fetch_campaign_history(self, lookback_days: int = 90) -> list[RoasDataPoint]:
        """Batch fetch all campaigns, last 90 days"""

# backend/connectors/tiktok_ads_client.py (MODIFY for real data)
class TikTokAdsConnector:
    async def fetch_daily_insights(self, date: datetime) -> list[RoasDataPoint]:
        """
        Call Business API: /campaign/get/?fields=spend,convert
        Returns: spend, conversions, clicks, impressions
        """

# backend/integrations/shopify_client.py (MODIFY for real data)
class ShopifyConnector:
    async def fetch_orders(self, since: datetime) -> list[Order]:
        """
        GraphQL: Orders + attribution tags (utm_source, referrer)
        Returns: order_id, customer_id, total, source, timestamp
        """
    
    async def deduplicate_orders(self, orders: list[Order]) -> list[Order]:
        """
        Group by customer_id + product_id + 7-day window
        Returns: deduplicated orders with primary attribution
        """
```

**Storage**:
```python
# backend/data/database.py (NEW)
class RoasStore:
    def __init__(self, db_url: str):
        # DuckDB or PostgreSQL
        # Table: roas_daily (date, product_id, platform, spend, revenue, roas, ...)
        # Index: (date, product_id), (date, platform)
        # Retention: 24+ months (for LTV cohorts)
    
    def append_daily_insights(self, insights: list[RoasDataPoint]) -> None:
        """Upsert daily aggregated ROAS"""
    
    def query_product_history(self, product_id: str, days: int) -> DataFrame:
        """Return time series for this product"""
```

### 1.2 Product Discovery Dataset

**Current Schema** (Synthetic):
```python
# core/signals.py (mock)
def top_opportunities():
    return [{"id": "product_1", "trend_score": 0.8}]
```

**New Schema** (Real):
```python
# backend/data/product_repository.py (NEW)
@dataclass
class DiscoveredProduct:
    supplier_id: str  # "shopify_own" | "aliexpress_12345" | "spocket_67890"
    sku: str
    name: str
    category: str
    
    # Signals
    trends_mentioned: int  # Reddit/Twitter mentions, last 7 days
    search_interest: float  # Google Trends (0-100 scale)
    supplier_stock: int  # Units available
    
    # Economics
    cost_usd: float  # Landed cost (supplier + shipping)
    suggested_retail: float  # Market-validated price
    estimated_return_rate: float  # By category
    
    # Validation
    successful_sellers: int  # How many sellers on Amazon/eBay selling this
    price_points: list[float]  # Competitive pricing
    average_rating: float  # 1-5 stars across sellers
    reviews_count: int
    
    # Risk
    trend_direction: str  # "rising" | "peak" | "declining"
    market_saturation: float  # 0-1 (how many sellers competing)
    supply_risk: str  # "abundant" | "moderate" | "scarce"
    
    # Discovery meta
    discovered_from: str  # "reddit" | "google_trends" | "supplier_feed"
    discovery_date: datetime
    confidence: float  # 0-1 (how certain this is a good find)

class ProductRepository:
    def get_trending_products(self, category: str = None, days: int = 7) -> list[DiscoveredProduct]:
        """Top products mentioned in social media + Google Trends"""
    
    def get_validated_products(self, min_confidence: float = 0.7) -> list[DiscoveredProduct]:
        """Products with multiple validation signals"""
    
    def get_supplier_catalog(self, supplier: str) -> list[DiscoveredProduct]:
        """All available products from this supplier"""
```

**Data Sources**:
```python
# backend/discovery/reddit_trends.py (REAL - parse actual r/entrepreneur posts)
class RedditDiscovery:
    async def fetch_trending_products(self, subreddits: list[str]) -> list[DiscoveredProduct]:
        """
        Query r/entrepreneur, r/ecommerce, r/dropshipping, r/shopify
        Parse posts for product mentions + upvotes + comments
        Extract: product name, category, success signals
        """

# backend/discovery/google_trends.py (REAL - call Trends API)
class GoogleTrendsDiscovery:
    async def fetch_trending_keywords(self, category: str) -> list[DiscoveredProduct]:
        """
        Call Google Trends API: compare_keywords()
        Returns: Search interest by region + time
        """

# backend/discovery/influencer_analysis.py (NEW)
class InfluencerAnalysis:
    async def get_viral_content(self, platform: str) -> list[dict]:
        """
        TikTok: Fetch trending #FYP content by category
        Instagram: Top performing posts in hashtags
        YouTube: Trending videos in product categories
        Returns: video_id, views, likes, creator, product_mentioned, engagement_rate
        """

# backend/discovery/supplier_feeds.py (REAL - Spocket, CJ, Printful APIs)
class SupplierCatalogDiscovery:
    async def fetch_trending_on_supplier(self, supplier: str) -> list[DiscoveredProduct]:
        """
        Spocket: GET /products?sort=trending
        CJ: GET /product/search?filters=new_products
        Printful: GET /products?sort=trending
        """

# backend/discovery/competitor_monitoring.py (NEW)
class CompetitorMonitoring:
    async def find_successful_sellers(self, product: str) -> list[dict]:
        """
        AliExpress: Search this product, get top sellers + sales count
        Amazon: Get seller reviews, price history
        eBay: Completed listings, final sale prices
        Returns: seller_name, sales_volume, rating, price_history
        """
```

### 1.3 Publicity/Marketing Success Dataset

**Current Schema** (None - Phase 7-8 untested):
```python
# core/creative/hook_performance.py (mock)
# Tracks made-up hook performance
```

**New Schema** (Real):
```python
# backend/data/marketing_repository.py (NEW)
@dataclass
class SuccessfulCreative:
    creator_id: str  # TikTok/Instagram handle or agency ID
    platform: str  # "tiktok" | "instagram" | "youtube"
    content_id: str  # Video/post ID
    
    # Creative Elements
    category: str  # "problem_solution" | "social_proof" | "urgency"
    hook_type: str  # "pain_point" | "curiosity" | "authority"
    trend_used: str  # Hashtag, sound, filter
    
    # Performance (Real)
    product_featured: str  # SKU
    views: int
    likes: int
    comments: int
    shares: int
    saves: int
    
    # Business Metrics
    estimated_purchases: int  # From linked tracker / affiliate data
    estimated_cac: float  # Cost per acquisition (if paid partnership)
    engagement_rate: float  # (likes + comments + shares) / views
    
    # Replicability
    creator_follower_count: int
    creator_engagement_rate: float
    creation_cost: float  # If paid for content
    timeframe: str  # How long was this content successful (days)
    
    # Meta
    discovered_date: datetime
    category_success_rate: float  # How often this category works

class MarketingRepository:
    def get_successful_hooks(self, category: str) -> list[SuccessfulCreative]:
        """
        Top-performing creative hooks for product category
        Real data from influencer performance
        """
    
    def get_viral_patterns(self, platform: str, lookback_days: int = 30) -> list[dict]:
        """
        What patterns made content go viral last month?
        (sound + hook + creator_size + timing)
        """
    
    def get_trending_creators(self, niche: str) -> list[dict]:
        """
        Creators with rising engagement in this niche
        Their recent content, engagement rates, typical CPM
        """
    
    def get_category_playbook(self, category: str) -> dict:
        """
        Aggregated best practices for this category:
        - Most common hooks
        - Best platforms (TikTok vs Instagram vs YouTube)
        - Typical engagement rates
        - Time-to-viral patterns
        """
```

**Data Sources**:
```python
# backend/discovery/viral_content.py (NEW)
class ViralContentAnalysis:
    async def fetch_viral_tiktoks(self, category: str, days: int = 7) -> list[SuccessfulCreative]:
        """
        TikTok Research API or unofficial scraping:
        - Trending videos in category
        - Product mentioned
        - Creator info
        - Performance metrics
        """
    
    async def fetch_successful_ads(self, product_category: str) -> list[SuccessfulCreative]:
        """
        Facebook Ad Library (public):
        - All ads running for this product category
        - Creative copy, images, video
        - Estimated spend + duration running
        Returns: what ads work for this category
        """

# backend/discovery/influencer_database.py (NEW)
class InfluencerDatabase:
    async def get_top_creators(self, niche: str, min_followers: int = 10000) -> list[dict]:
        """
        Third-party APIs: HypeAuditor, AspireIQ, or TikTok API
        Returns: creator handle, follower count, engagement rate, typical rate
        """
    
    async def get_creator_performance(self, creator_id: str) -> list[SuccessfulCreative]:
        """
        Historical posts from this creator + engagement metrics
        What content works for them?
        """

# backend/discovery/ad_library.py (NEW)
class AdLibraryAnalysis:
    async def fetch_running_ads(self, category: str) -> list[dict]:
        """
        Facebook Ad Library (https://facebook.com/ads/library)
        Returns: advertiser, creative copy, estimated spend, since_date
        Best ads are ones running the longest = proven winners
        """
```

---

## Phase 2: Real Data Pipeline (Weeks 2-3)

### 2.1 Ingestion Architecture

```python
# backend/data/ingestion_pipeline.py (NEW)

class DataPipeline:
    """
    Daily ETL: Extract → Transform → Load
    Runs once per day, aggregates previous 24 hours
    """
    
    async def run_daily_ingestion(self):
        # 1. Fetch data from all sources (parallel)
        roas_data = await fetch_roas_from_platforms()  # Meta, TikTok, Shopify
        products = await fetch_trending_products()     # Reddit, Google Trends, Suppliers
        creatives = await fetch_viral_content()        # TikTok, Instagram, Ad Library
        
        # 2. Transform & deduplicate
        roas_deduplicated = deduplicate_cross_platform(roas_data)
        products_validated = validate_product_data(products)
        creatives_scored = score_creative_performance(creatives)
        
        # 3. Load into database
        await roas_store.append_daily_insights(roas_deduplicated)
        await product_repo.upsert_products(products_validated)
        await marketing_repo.upsert_creatives(creatives_scored)
        
        # 4. Log event for monitoring
        event_store.append(
            workflow_id="data_pipeline",
            event="daily_ingestion_complete",
            data={
                "roas_records": len(roas_deduplicated),
                "products_discovered": len(products_validated),
                "creatives_analyzed": len(creatives_scored),
                "timestamp": datetime.now(),
            }
        )
```

**Ingestion Schedule**:
```
00:00 UTC:  Fetch previous day's data from all platforms
01:00 UTC:  Deduplicate & validate
02:00 UTC:  Load into database
02:30 UTC:  Generate alerts for anomalies (e.g., ROAS dropped 50%)
03:00 UTC:  Decision engine uses fresh real data
```

### 2.2 Error Handling & Fallback

```python
# backend/data/ingestion_resilience.py (NEW)

class ResilientPipeline:
    """
    Handles API failures, rate limits, incomplete data gracefully
    """
    
    async def fetch_with_fallback(self, source: str) -> list[dict]:
        try:
            # Try primary source
            return await source.fetch()
        except RateLimitError:
            # Wait and retry
            await asyncio.sleep(60)
            return await source.fetch()
        except CredentialError:
            # Log alert, use cached data from yesterday
            logger.error(f"{source} credential error")
            return await load_cached_data(source, days_old=1)
        except APIError as e:
            # Log, use cached data
            logger.warning(f"{source} API error: {e}")
            return await load_cached_data(source, days_old=1)
    
    async def run_resilient_pipeline(self):
        """
        Try to ingest from all sources, use whatever succeeds
        Ensures no single API outage breaks the whole system
        """
        sources = {
            "meta": self.meta_connector,
            "tiktok": self.tiktok_connector,
            "shopify": self.shopify_connector,
            "reddit": self.reddit_connector,
            "google_trends": self.google_trends_connector,
        }
        
        results = {}
        for source_name, connector in sources.items():
            results[source_name] = await self.fetch_with_fallback(connector)
        
        # Use whatever succeeded; alert on failures
        return results
```

### 2.3 Migration: Switch Decision Engine from Mock to Real

```python
# backend/execution/loop.py (MODIFY)

async def run_cycle(state: SystemState):
    """
    BEFORE: Call _generate_roas() (mock)
    AFTER: Call roas_repository.get_current_roas() (real data)
    """
    
    # OLD (mock):
    # market_roas = _generate_roas()  # random.uniform(0.5, 3.0)
    
    # NEW (real):
    market_roas = await roas_repository.get_latest_actual_roas(
        products=state.active_products,
        lookback_hours=24  # Last 24 hours of real data
    )
    
    # Rest of decision logic remains the same
    decisions = await decide(state, market_roas)
    return decisions
```

---

## Phase 3: Discovery & Validation Wiring (Weeks 3-4)

### 3.1 Product Discovery Pipeline Integration

```python
# backend/discovery/discovery_engine.py (MODIFY)

class DiscoveryEngine:
    """
    Real-time integration with:
    - Trending products (Reddit, Google Trends)
    - Supplier catalogs (Spocket, CJ, Printful)
    - Competitor success signals (Amazon, eBay, AliExpress)
    """
    
    async def identify_opportunities(self) -> list[ProductOpportunity]:
        """
        Daily: Find products worth launching
        """
        # 1. Fetch trending signals
        reddit_trends = await reddit_discovery.fetch_trending_products()
        google_trends = await google_trends_discovery.fetch_trending_keywords()
        supplier_new = await supplier_feeds.fetch_trending_on_supplier()
        
        # 2. Validate with market data
        opportunities = []
        for product in reddit_trends + google_trends + supplier_new:
            # Check: Is this profitable?
            margin = await margin_calculator.calculate_margin(
                supplier_cost=product.cost_usd,
                retail_price=product.suggested_retail,
                category=product.category
            )
            
            if margin["margin_status"] == "profitable":
                # Check: Can we beat competitors?
                competitors = await competitor_monitoring.find_successful_sellers(product.name)
                saturation = len(competitors) / 10.0  # Normalize
                
                if saturation < 0.7:  # <70% saturation threshold
                    opportunities.append(ProductOpportunity(
                        product=product,
                        margin=margin,
                        trend_strength=product.trends_mentioned + (google_trends[product] * 10),
                        market_saturation=saturation,
                        confidence=0.8
                    ))
        
        # 3. Rank by ROI potential
        return sorted(opportunities, key=lambda x: x.trend_strength * (1 - x.market_saturation))
```

### 3.2 Creative/Publicity Strategy Integration

```python
# backend/discovery/strategy_playbook.py (NEW)

class StrategyPlaybook:
    """
    For each product category, recommend:
    - Best creators to partner with
    - Most effective creative hooks
    - Optimal platforms (TikTok vs Instagram vs YouTube)
    - Estimated CAC based on category
    """
    
    async def generate_playbook(self, category: str) -> dict:
        """
        For a new product in this category, recommend go-to-market strategy
        """
        # 1. Fetch historical success data
        successful_creatives = await marketing_repo.get_successful_hooks(category)
        viral_patterns = await viral_content.fetch_viral_patterns(category)
        top_creators = await influencer_db.get_top_creators(category)
        
        # 2. Aggregate patterns
        playbook = {
            "best_platforms": self._rank_platforms(successful_creatives),
            "proven_hooks": self._extract_hook_patterns(successful_creatives),
            "recommended_creators": top_creators[:10],
            "estimated_cac": self._estimate_cac(category, successful_creatives),
            "content_template": self._generate_template(successful_creatives),
            "expected_engagement_rate": self._benchmark_engagement(category),
        }
        
        return playbook
    
    def _rank_platforms(self, creatives: list[SuccessfulCreative]) -> dict:
        """
        TikTok vs Instagram vs YouTube for this category
        Returns: {platform: (win_rate, avg_engagement, avg_cac)}
        """
```

---

## Phase 4: Validation & Testing (Weeks 4-5)

### 4.1 Real Data Validation Framework

```python
# backend/validation/real_data_validator.py (NEW)

class RealDataValidator:
    """
    Verify real data is better/different than mock data
    """
    
    def validate_roas_realism(self):
        """
        ROAS in mock: uniform 0.5-3.0
        ROAS in real: Should be bi-modal (winners around 2-4, losers around 0.3-0.7)
        Alert if real ROAS distribution looks like fake data
        """
        mock_mean = 1.75
        real_mean = roas_repository.get_mean_roas(days=30)
        
        if abs(real_mean - mock_mean) < 0.1:
            logger.warning("Real ROAS looks like mock data - validation failing?")
        
        # Check for realistic skew (winners rarer than losers)
        percentiles = roas_repository.get_percentiles()
        if percentiles[0.9] < 2.0:  # Top 10% should be >2.0
            logger.warning("Real ROAS distribution looks suspicious")
    
    def validate_product_discovery(self):
        """
        Discovered products should:
        - Come from multiple sources (not just one API)
        - Have trending signals + supplier availability (not just trending)
        - Show realistic supply/demand (not infinite inventory)
        """
        discovered = product_repository.get_all_discovered()
        
        sources = set(p.discovered_from for p in discovered)
        if len(sources) < 3:
            logger.warning("Products only from 1-2 sources, need more signals")
        
        # Check: Do discovered products actually sell?
        success_rate = sum(
            1 for p in discovered
            if roas_repository.get_product_roas(p.sku, days=30)  # Has actual sales
        ) / len(discovered)
        
        logger.info(f"Product discovery success rate: {success_rate:.1%}")
    
    def validate_creative_strategies(self):
        """
        Recommended creatives should match historical success patterns
        """
        strategies = strategy_playbook.get_all_recommended()
        
        for strategy in strategies:
            # Is this creator actually effective in this category?
            creator_success = await marketing_repo.get_creator_performance(strategy.creator_id)
            
            if not creator_success:
                logger.warning(f"Creator {strategy.creator_id} not validated with real data")
```

### 4.2 A/B Testing Real Data vs Mock

```python
# backend/validation/ab_test_real_vs_mock.py (NEW)

class RealVsMockComparison:
    """
    Run decisions on both real and mock data
    Measure: Do we make different decisions? Are they better?
    """
    
    async def compare_discovery(self):
        """
        Mock discovery: random products
        Real discovery: trending products
        Measure: Which leads to more profitable launches?
        """
        mock_products = self.generate_mock_products(50)
        real_products = await product_repository.get_trending_products(limit=50)
        
        # Score both
        mock_scores = [self.score_product(p) for p in mock_products]
        real_scores = [self.score_product(p) for p in real_products]
        
        # Compare
        print(f"Mock products avg score: {mean(mock_scores):.2f}")
        print(f"Real products avg score: {mean(real_scores):.2f}")
        # Expected: Real > Mock by 30-50%
    
    async def compare_roas_prediction(self):
        """
        Use mock ROAS data vs real ROAS data
        Train decision model on both
        Test: Which predicts future ROAS better?
        """
        # Split data: 80% train, 20% test
        real_data = await roas_repository.get_historical(days=90)
        train, test = real_data[:72], real_data[72:]
        
        # Train models
        mock_model = train_model_on_mock_data()
        real_model = train_model_on_real_data(train)
        
        # Test
        mock_mae = mean_absolute_error(mock_model.predict(test), test.roas)
        real_mae = mean_absolute_error(real_model.predict(test), test.roas)
        
        print(f"Mock model MAE: {mock_mae:.2f}")
        print(f"Real model MAE: {real_mae:.2f}")
        # Expected: Real < Mock (better predictions)
```

---

## Phase 5: Integration with Live System (Week 5-6)

### 5.1 Switch Data Sources with Flag

```python
# backend/execution/loop.py (MODIFY)

class ExecutionLoop:
    def __init__(self, use_real_data: bool = False):
        self.use_real_data = use_real_data
        # use_real_data = os.getenv("USE_REAL_DATA", "false").lower() == "true"
    
    async def run_cycle(self, state: SystemState):
        if self.use_real_data:
            # Fetch real ROAS, real products, real strategies
            market_roas = await roas_repository.get_latest_actual_roas()
            products = await product_repository.get_trending_products()
            strategies = await strategy_playbook.generate_recommendations()
        else:
            # Use mock data (existing behavior)
            market_roas = self._generate_mock_roas()
            products = self._generate_mock_products()
            strategies = self._generate_mock_strategies()
        
        # Identical decision logic, just different data
        decisions = await decide(state, market_roas, products, strategies)
        return decisions
```

### 5.2 Staged Real Data Activation

```bash
# Week 5 (Pilot)
export USE_REAL_DATA=false  # Still using mock
export LOG_REAL_DATA=true   # But collecting real data in parallel

# Week 5-6 (Validation)
# Run both paths: mock decisions vs real-data decisions
# Log side-by-side comparison

# Week 6 (Flip)
export USE_REAL_DATA=true   # Switch to real data
# All Phase 1-8 logic now using real ROAS, real products, real strategies
```

---

## Data Requirements Summary

### Volume Needed

| Data Source | Minimum | Ideal | Refresh |
|-------------|---------|-------|---------|
| Historical ROAS | 12 months | 24 months | Daily |
| Product Catalog | 500 products | 50k products | Daily |
| Reddit Trending | Daily top 50 | 500 posts/day | Real-time |
| Google Trends | 100 keywords | 1000 keywords | Daily |
| Viral Content | 100 videos/month | 10k videos/month | Daily |
| Influencer DB | 100 creators/niche | 10k creators | Weekly |
| Ad Library Ads | 1000 ads/category | 100k ads | Daily |
| Supplier Feeds | 10k SKUs | 1M SKUs | Daily |

### Storage & Compute

```
Monthly Data Volume:
- ROAS: 30 days × 5 platforms × 50 products = ~7,500 records (~5 MB)
- Products: 50k discovered × 30 days = ~1.5M records (~2 GB/month)
- Creatives: 10k videos × 10 metrics = ~100k records (~500 MB)
- Total: ~3 GB/month, ~36 GB/year

Database: DuckDB or PostgreSQL
  - ROAS table: index (date, product_id), (date, platform)
  - Products table: index (category, trend_date)
  - Creatives table: index (platform, category, engagement_rate)

Compute:
- Ingestion: 10 min/day (parallel API calls)
- Validation: 5 min/day
- Analysis: 20 min/day (weekly: strategy playbook regeneration)
- Total: <45 min/day overhead
```

---

## Implementation Roadmap

### Week 1-2: Data Architecture
- [ ] Design schemas (ROAS, Products, Creatives)
- [ ] Build database (DuckDB/PostgreSQL)
- [ ] Create repository interfaces
- [ ] Set up connector frameworks

### Week 2-3: Real Data Ingestion
- [ ] Implement Meta Ads connector
- [ ] Implement TikTok Ads connector
- [ ] Implement Shopify order deduplication
- [ ] Implement Reddit/Google Trends scrapers
- [ ] Implement influencer/ad library analysis

### Week 3-4: Integration Points
- [ ] Wire real ROAS into decision engine
- [ ] Integrate product discovery with signal generation
- [ ] Integrate strategy playbook with creative selection

### Week 4-5: Validation & Testing
- [ ] Real data validator framework
- [ ] A/B testing: real vs mock decisions
- [ ] Comparison: Are real-data decisions better?

### Week 5-6: Staged Rollout
- [ ] Parallel run (mock + real)
- [ ] Monitoring & alerts
- [ ] Flip flag to real data (USE_REAL_DATA=true)

### Week 6+: Production Operation
- [ ] Daily ingestion pipeline
- [ ] Weekly strategy regeneration
- [ ] Monthly data quality audits

---

## Risk Mitigation

### Data Quality Risks
- **Risk**: Real data is noisy/incomplete
- **Mitigation**: Cache 1-day-old data as fallback, use mock if fetch fails

### API Rate Limits
- **Risk**: API calls exceeding rate limits
- **Mitigation**: Batch requests, implement exponential backoff, queue system

### Credential Exposure
- **Risk**: API keys/tokens in code
- **Mitigation**: Use environment variables, secrets manager (AWS Secrets, GCP Secret Manager)

### Data Privacy
- **Risk**: PII in Shopify/customer data
- **Mitigation**: Hash customer IDs, never log names/emails, comply with GDPR/CCPA

### Decision Quality Regression
- **Risk**: Real data leads to worse decisions
- **Mitigation**: A/B test real vs mock, monitor ROI live, rollback flag if regression

---

## Success Metrics

After real data is wired (Week 6+):

| Metric | Mock Data | Real Data | Target |
|--------|-----------|-----------|--------|
| Avg ROAS | 1.75 | ? | Should be more realistic |
| Product discovery success | N/A | % profitable launches | ≥60% |
| Creative strategy accuracy | N/A | % successful creator partnerships | ≥70% |
| Decision quality (MAE) | N/A | ROAS prediction error | <0.3 |
| System latency | <1s/cycle | Should remain <1s | ≤1.5s |

---

## Next Steps

1. **Immediate**: Audit what credentials/API access already exists
2. **Week 1**: Design final schemas based on available data sources
3. **Week 2**: Build first connector (recommend: Shopify orders, easiest)
4. **Week 3**: Build second connector (recommend: Meta Ads API)
5. **Week 4**: Integrate into decision engine with flag
6. **Week 5**: A/B test real vs mock
7. **Week 6**: Flip flag to production

---

**Questions?**
- Which APIs do you have credentials for?
- What's the scale of your Shopify store (products, monthly orders)?
- Should we prioritize specific data sources (e.g., focus on TikTok first)?
- Any compliance requirements (GDPR, CCPA, data privacy)?
> **Archived — superseded by `README.md`.** Kept for history; do not treat claims below as current.
> Current replacement: `README.md`.
