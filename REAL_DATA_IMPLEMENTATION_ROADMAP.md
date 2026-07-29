# MarketOS Real Data Implementation Roadmap

**Phase**: Weeks 1-6 (Parallel with Production Monitoring)  
**Goal**: Replace 100% synthetic data with real market datasets  
**Status**: Planning Phase (Ready to Begin)

---

## Priority & Sequencing

### Tier 1: MUST HAVE (Weeks 1-3)
These directly replace core mock data and unblock Phases 7-8 validation:

1. **Real ROAS Data** (Week 1-2)
   - Why: Decision engine currently uses random ROAS
   - Sources: Shopify orders + Meta/TikTok ads spend/revenue
   - Impact: Capital allocation now based on real performance
   - Risk if skipped: Phases 7-8 validation meaningless (tuning on fake data)

2. **Product Discovery from Real Trends** (Week 2-3)
   - Why: Currently hardcoded fake products
   - Sources: Reddit, Google Trends, supplier catalogs
   - Impact: Launch decisions based on actual market demand signals
   - Risk if skipped: Discover products no one wants

3. **Creative Strategy Validation** (Week 3)
   - Why: Phase 7 (Creative Fatigue) untested with real content
   - Sources: TikTok/Instagram viral content, Facebook Ad Library
   - Impact: Fatigue detection & refresh signals validated
   - Risk if skipped: Recommend creatives that don't work

### Tier 2: SHOULD HAVE (Weeks 4-5)
Enhance with market context:

4. **Competitor & Market Validation** (Week 4)
   - Why: Validate our products against competitors
   - Sources: Amazon, eBay, AliExpress seller data
   - Impact: Market saturation scoring, pricing benchmarks
   - Risk if skipped: Launch into saturated markets

5. **Creator Recommendations** (Week 5)
   - Why: Phase 8 (Organic Channel) needs real influencer data
   - Sources: TikTok/Instagram creator databases, engagement rates
   - Impact: Partner with proven creators for seeding
   - Risk if skipped: Seed with ineffective creators

### Tier 3: NICE TO HAVE (Week 6+)
Deep market intelligence:

6. **Supplier Reliability Tracking** (Week 6+)
   - Why: Phase 6 needs real stockout/delay data
   - Sources: Order fulfillment data from Shopify + supplier feedback
   - Impact: Actual supplier reliability scores (not constant)

7. **Customer LTV & Repeat Purchase Cohorts** (Week 6+)
   - Why: Phase 6 LTV adjustment needs real customer data
   - Sources: Shopify repeat customers, email/SMS engagement
   - Impact: Products with repeat potential correctly valued

---

## Week-by-Week Execution Plan

### Week 1: Real ROAS Data Integration (Tier 1)

**Days 1-2: API Access & Credential Setup**

```bash
# Checklist
☐ Shopify Admin API access token (scope: read_products, read_orders, read_fulfillments)
☐ Meta Business Account + App ID (for Graph API)
☐ TikTok Business Account + API access (OAuth)
☐ Store credentials in .env or AWS Secrets Manager

# Verify
python backend/connectors/shopify_client.py --test-connection
python backend/connectors/meta_ads_client.py --test-connection
python backend/connectors/tiktok_ads_client.py --test-connection
```

**Days 3-5: Implement ROAS Repository & Deduplication**

```python
# New file: backend/data/repositories/roas_repository.py (400 LOC)

class RoasRepository:
    def __init__(self, db_url: str = "duckdb:///data/marketos.db"):
        self.db = DuckDB(db_url)
        self._init_schema()
    
    def _init_schema(self):
        """Create tables: roas_daily, orders_deduped, platform_insights"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS roas_daily (
                date DATE,
                product_id VARCHAR,
                platform VARCHAR,  -- 'meta', 'tiktok', 'organic'
                spend FLOAT,
                revenue FLOAT,
                roas FLOAT,
                clicks INT,
                conversions INT,
                platform_reported_roas FLOAT,
                deduplication_confidence FLOAT,
                PRIMARY KEY (date, product_id, platform)
            )
        """)
    
    async def ingest_shopify_orders(self, orders: list[Order]):
        """
        Raw orders from Shopify (with utm_source, referrer, timestamps)
        Group by customer + 7-day window to deduplicate multi-touch
        """
    
    async def ingest_meta_insights(self, insights: list[MetaInsight]):
        """Raw campaign insights from Meta Ads API"""
    
    async def ingest_tiktok_insights(self, insights: list[TikTokInsight]):
        """Raw campaign insights from TikTok Ads API"""
    
    def deduplicate_cross_platform(self) -> dict:
        """
        Multi-touch attribution reconciliation:
        - Same customer, same product, within 7 days
        - Assign to "first click" or "last click" (configurable)
        Returns: deduped ROAS per product
        """
    
    def get_product_roas(self, product_id: str, days: int = 30) -> list[RoasDataPoint]:
        """Time series ROAS for one product"""
    
    def get_platform_comparison(self, days: int = 30) -> dict:
        """Meta vs TikTok performance comparison"""

# New file: backend/connectors/shopify_client.py (MODIFY for real orders)

class ShopifyConnector:
    def __init__(self, store_url: str, access_token: str):
        self.store_url = store_url
        self.client = ShopifyAPI(access_token)
    
    async def fetch_orders(self, since: datetime, limit: int = 250):
        """
        GraphQL query:
        {
          orders(first: 100, after: cursor) {
            edges {
              node {
                id
                createdAt
                totalPrice
                source  # utm_source
                referrerCode
                lineItems {
                  product { handle }
                  quantity
                  priceSet { shopMoney { amount } }
                }
                customer { id email }
              }
            }
          }
        }
        """
    
    async def deduplicate_orders(self, orders: list[Order]) -> list[Order]:
        """
        Algorithm:
        1. Group by customer_id + product_handle + 7-day window
        2. If >1 order: likely multi-touch
        3. Assign primary channel: last_click (default)
        4. Mark others as "duplicate"
        Returns: one row per deduped order
        """

# New file: backend/connectors/meta_ads_client.py (MODIFY for real data)

class MetaAdsConnector:
    def __init__(self, access_token: str, ad_account_id: str):
        self.access_token = access_token
        self.ad_account_id = ad_account_id  # act_XXXXXXXXX
    
    async def fetch_daily_insights(self, date: datetime):
        """
        GET /me/adsets?fields=insights.date_start(DATE).date_stop(DATE)
        Fields: spend, impressions, clicks, purchase_conversion_value, purchase_roas
        """
    
    async def fetch_campaign_performance(self, campaign_id: str, days: int = 90):
        """Historical campaign performance"""

# New file: backend/connectors/tiktok_ads_client.py (MODIFY for real data)

class TikTokAdsConnector:
    def __init__(self, access_token: str, advertiser_id: str):
        self.access_token = access_token
        self.advertiser_id = advertiser_id
    
    async def fetch_daily_insights(self, date: datetime):
        """
        GET /campaign/get/?fields=spend,convert,cvr,cost
        Aggregate to product level (if tracking available)
        """

# Ingestion job (daily, 00:00 UTC)

async def daily_roas_ingestion():
    repo = RoasRepository()
    
    # 1. Fetch from all sources (parallel)
    shopify_orders = await shopify.fetch_orders(yesterday)
    meta_insights = await meta.fetch_daily_insights(yesterday)
    tiktok_insights = await tiktok.fetch_daily_insights(yesterday)
    
    # 2. Ingest
    await repo.ingest_shopify_orders(shopify_orders)
    await repo.ingest_meta_insights(meta_insights)
    await repo.ingest_tiktok_insights(tiktok_insights)
    
    # 3. Deduplicate
    deduped = repo.deduplicate_cross_platform()
    
    # 4. Log
    logger.info(f"ROAS ingestion: {len(deduped)} products, "
                f"avg ROAS {deduped_roas.mean():.2f}")
```

**Days 5-7: Validation & Testing**

```python
# Tests: tests/test_roas_integration.py (300 LOC)

def test_roas_repository():
    """
    1. Insert mock ROAS data
    2. Query by product/platform
    3. Verify time series
    """

def test_shopify_deduplication():
    """
    1. Create 3 orders from same customer, same product, 3-day spread
    2. Deduplicate
    3. Verify: 1 order counted, 2 marked as duplicate
    """

def test_cross_platform_reconciliation():
    """
    1. Insert Meta: $100 spend, $400 revenue (ROAS 4.0)
    2. Insert TikTok: $50 spend, $150 revenue (ROAS 3.0)
    3. Insert Shopify: $480 revenue total
    4. Deduplicate (some orders from both platforms)
    5. Verify: Final ROAS = $480 / $150 spend = 3.2
    """

# Integration test
async def test_real_data_flow():
    # Fetch real data from staging Shopify store
    orders = await shopify_staging.fetch_orders(yesterday)
    
    # Process through deduplication
    deduped = await repo.deduplicate_cross_platform(orders)
    
    # Verify: deduped ROAS is lower than raw ROAS
    # (because we removed double-counted revenue)
    assert deduped.roas < raw_roas
```

---

### Week 2: Product Discovery & Trends Integration (Tier 1)

**Days 1-3: Real Trend Data Ingestion**

```python
# New file: backend/data/repositories/product_repository.py (400 LOC)

class ProductRepository:
    def __init__(self, db_url: str):
        self.db = DuckDB(db_url)
        self._init_schema()
    
    def _init_schema(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS discovered_products (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                category VARCHAR,
                supplier_id VARCHAR,  -- aliexpress_12345, spocket_67890, etc
                supplier_sku VARCHAR,
                cost_usd FLOAT,
                suggested_retail FLOAT,
                
                -- Signals
                trends_mentioned INT,  -- Reddit/Twitter mentions, last 7d
                search_interest FLOAT,  -- Google Trends 0-100
                successful_sellers INT,  -- Amazon/eBay/AliExpress count
                avg_rating FLOAT,       -- 1-5 stars
                reviews_count INT,
                
                -- Risk
                market_saturation FLOAT,  -- 0-1
                trend_direction VARCHAR,   -- rising, peak, declining
                supply_risk VARCHAR,       -- abundant, moderate, scarce
                
                -- Meta
                discovered_from VARCHAR,  -- reddit, google_trends, supplier_feed, ad_library
                discovered_date TIMESTAMP,
                confidence FLOAT,         -- 0-1
                
                PRIMARY KEY (id)
            )
        """)
    
    async def add_discovered_product(self, product: DiscoveredProduct):
        """Upsert a newly discovered product"""
    
    async def get_trending_products(self, category: str = None, 
                                    limit: int = 50, 
                                    min_confidence: float = 0.6) -> list[DiscoveredProduct]:
        """Return top trending products"""
    
    async def get_validated_products(self, min_confidence: float = 0.75) -> list[DiscoveredProduct]:
        """Products with multiple validation signals"""

# Real data sources

# backend/discovery/reddit_discovery.py (NEW - 300 LOC)

class RedditDiscovery:
    def __init__(self):
        self.client = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent="MarketOS/1.0"
        )
    
    async def fetch_trending_products(self, subreddits: list[str] = None) -> list[dict]:
        """
        Subreddits: r/entrepreneur, r/ecommerce, r/dropshipping, r/shopify
        Extract: product mentions, upvotes, comments
        Return: [{"name": "...", "mentions": N, "score": X}, ...]
        """
        if subreddits is None:
            subreddits = ["entrepreneur", "ecommerce", "dropshipping", "shopify"]
        
        products = {}
        for subreddit_name in subreddits:
            sub = self.client.subreddit(subreddit_name)
            
            # Get top posts from last 7 days
            for post in sub.top(time_filter="week", limit=50):
                # Extract product mentions from title + comments
                mentions = self._extract_products(post.title, post.selftext)
                
                for product_name in mentions:
                    if product_name not in products:
                        products[product_name] = {"mentions": 0, "subreddit_scores": []}
                    
                    products[product_name]["mentions"] += 1
                    products[product_name]["subreddit_scores"].append(post.score)
        
        # Rank by mentions + upvotes
        return sorted(
            [{"name": k, "mentions": v["mentions"], "avg_score": mean(v["subreddit_scores"])} 
             for k, v in products.items()],
            key=lambda x: x["mentions"] * log(x["avg_score"] + 1),
            reverse=True
        )
    
    def _extract_products(self, title: str, body: str) -> list[str]:
        """
        NLP: Extract product names from text
        Simple version: Look for quotes, "X is great", mentions of brand/product
        Advanced: Use NER (spaCy) or LLM
        """

# backend/discovery/google_trends.py (NEW - 200 LOC)

class GoogleTrendsDiscovery:
    def __init__(self):
        # Use pytrends (unofficial) or Google Trends API (official, requires auth)
        self.trends = TrendReq(hl='en-US')
    
    async def fetch_trending_keywords(self, 
                                      categories: list[str] = None) -> list[dict]:
        """
        Categories: home & garden, electronics, apparel, beauty, sports
        Returns: [{"keyword": "...", "interest": 0-100, "trend": "rising|stable|declining"}, ...]
        """
        if categories is None:
            categories = ["home & garden", "electronics", "apparel", "beauty", "sports"]
        
        trends = []
        for category in categories:
            # Get trending searches by category
            trending = self.trends.trending_searches(pn=category)  # Fake API, use real one
            
            for keyword in trending:
                # Check trend direction
                self.trends.build_payload([keyword], timeframe='today 1-m')
                data = self.trends.interest_over_time()
                
                trend_direction = self._classify_trend(data)
                
                trends.append({
                    "keyword": keyword,
                    "interest": data.iloc[-1][keyword] * 100,  # Last value as interest
                    "trend": trend_direction,
                    "category": category
                })
        
        return sorted(trends, key=lambda x: x["interest"], reverse=True)

# backend/discovery/supplier_feeds.py (NEW - 300 LOC)

class SupplierCatalogDiscovery:
    def __init__(self):
        self.spocket = SpocketAPI(api_key=os.getenv("SPOCKET_API_KEY"))
        self.cj = CJDropshippingAPI(api_key=os.getenv("CJ_API_KEY"))
        self.printful = PrintfulAPI(api_key=os.getenv("PRINTFUL_API_KEY"))
    
    async def fetch_trending_on_spocket(self) -> list[dict]:
        """Spocket trending products"""
        response = await self.spocket.get("/products?sort=trending&limit=100")
        return response["products"]
    
    async def fetch_trending_on_cj(self) -> list[dict]:
        """CJ trending/new products"""
        response = await self.cj.get("/product/search?category=all&sort=new&limit=100")
        return response["products"]
    
    async def fetch_trending_on_printful(self) -> list[dict]:
        """Printful trending products"""
        response = await self.printful.get("/products?sort=trending&limit=100")
        return response["products"]

# Aggregation job (daily)

async def daily_product_discovery():
    product_repo = ProductRepository()
    
    # 1. Fetch from all sources (parallel)
    reddit_products = await reddit_discovery.fetch_trending_products()
    google_products = await google_trends_discovery.fetch_trending_keywords()
    spocket_products = await supplier_discovery.fetch_trending_on_spocket()
    cj_products = await supplier_discovery.fetch_trending_on_cj()
    printful_products = await supplier_discovery.fetch_trending_on_printful()
    
    # 2. Aggregate & deduplicate
    all_products = aggregate_and_deduplicate(
        reddit_products + google_products + spocket_products + cj_products + printful_products
    )
    
    # 3. Validate (check: profitable? market saturation?)
    validated = []
    for product in all_products:
        # Get supplier cost
        supplier_cost = await supplier_discovery.get_cost(product["name"])
        
        # Calculate margin
        margin = await margin_calculator.calculate_margin(
            supplier_cost=supplier_cost,
            retail_price=product.get("suggested_retail", supplier_cost * 3),
            category=product.get("category", "general")
        )
        
        if margin["margin_status"] == "profitable":
            # Check market saturation
            competitors = await competitor_monitoring.find_competitors(product["name"])
            saturation = len(competitors) / 10.0
            
            if saturation < 0.7:  # <70% saturation
                validated.append(DiscoveredProduct(
                    name=product["name"],
                    supplier_cost=supplier_cost,
                    suggested_retail=margin["retail_price"],
                    trends_mentioned=product.get("mentions", 0),
                    search_interest=product.get("search_interest", 0),
                    market_saturation=saturation,
                    confidence=calculate_confidence(product),
                    discovered_from=product["source"]
                ))
    
    # 4. Store
    for product in validated:
        await product_repo.add_discovered_product(product)
    
    logger.info(f"Discovery: {len(validated)} validated products from "
                f"{len(all_products)} found")
```

---

### Week 3: Creative Strategy & Publicity Wiring (Tier 1)

**Days 1-5: Real Creative Data & Strategy Generation**

```python
# New file: backend/data/repositories/marketing_repository.py (400 LOC)

class MarketingRepository:
    def __init__(self, db_url: str):
        self.db = DuckDB(db_url)
        self._init_schema()
    
    def _init_schema(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS successful_creatives (
                id VARCHAR PRIMARY KEY,
                creator_id VARCHAR,
                platform VARCHAR,  -- tiktok, instagram, youtube
                content_id VARCHAR,
                
                product_featured VARCHAR,
                category VARCHAR,
                hook_type VARCHAR,  -- problem_solution, social_proof, urgency
                
                views INT,
                likes INT,
                comments INT,
                shares INT,
                saves INT,
                engagement_rate FLOAT,
                
                estimated_cac FLOAT,
                estimated_conversions INT,
                
                creator_follower_count INT,
                creator_engagement_rate FLOAT,
                
                discovered_date TIMESTAMP,
                timeframe_days INT,  -- How long was this effective
                category_success_rate FLOAT,
                
                PRIMARY KEY (id)
            )
        """)
    
    async def get_successful_hooks(self, category: str) -> list[SuccessfulCreative]:
        """Top hooks for this category"""
    
    async def get_category_playbook(self, category: str) -> dict:
        """Aggregated strategy for category"""

# New file: backend/discovery/viral_content.py (NEW - 400 LOC)

class ViralContentAnalysis:
    def __init__(self):
        # TikTok Data API (or unofficial scraper)
        self.tiktok_api = TikTokDataAPI(api_key=os.getenv("TIKTOK_API_KEY"))
        # Instagram Graph API
        self.instagram = InstagramGraphAPI(access_token=os.getenv("INSTAGRAM_TOKEN"))
        # YouTube Data API
        self.youtube = YouTubeAPI(api_key=os.getenv("YOUTUBE_API_KEY"))
    
    async def fetch_viral_tiktoks(self, category: str, days: int = 7) -> list[dict]:
        """
        Fetch trending TikTok videos in a category
        Extract: creator, views, likes, product mentioned, hooks used
        """
        # TikTok trending endpoint (requires API access)
        trending = await self.tiktok_api.get_trending(
            category=category,
            limit=100,
            timeframe="last_7_days"
        )
        
        results = []
        for video in trending:
            # Analyze video content
            hooks = self._extract_hooks(video["description"], video["hashtags"])
            product = self._extract_product_mention(video["description"], video["content"])
            
            results.append({
                "creator_id": video["creator_id"],
                "content_id": video["video_id"],
                "views": video["view_count"],
                "likes": video["like_count"],
                "engagement_rate": (video["like_count"] + video["comment_count"]) / video["view_count"],
                "hooks": hooks,
                "product_featured": product,
                "platform": "tiktok"
            })
        
        return results
    
    async def fetch_successful_ads(self, category: str) -> list[dict]:
        """
        Facebook Ad Library (public):
        - All ads running for products in this category
        - Extract creative copy, hooks, estimated spend
        """
        # Facebook Ad Library API
        ads = await self._query_ad_library(category)
        
        # Ads running longest = proven winners
        ads_by_duration = sorted(ads, key=lambda x: x["days_running"], reverse=True)
        
        return ads_by_duration[:100]
    
    def _extract_hooks(self, description: str, hashtags: list[str]) -> list[str]:
        """
        NLP: Extract hook type from description
        - "How to..." → how_to
        - "OMG..." → urgency
        - "This changed my life" → transformation
        """
    
    def _extract_product_mention(self, description: str, content: str) -> str:
        """Extract product name/category from content"""

# New file: backend/discovery/strategy_playbook.py (NEW - 300 LOC)

class StrategyPlaybook:
    def __init__(self):
        self.marketing_repo = MarketingRepository()
        self.viral_content = ViralContentAnalysis()
        self.influencer_db = InfluencerDatabase()
    
    async def generate_playbook(self, category: str) -> dict:
        """
        For a new product in this category, recommend go-to-market strategy
        """
        # 1. What platforms work best for this category?
        successful_creatives = await self.marketing_repo.get_successful_hooks(category)
        platform_stats = self._analyze_platforms(successful_creatives)
        
        # 2. What hooks work?
        hook_analysis = self._analyze_hooks(successful_creatives)
        
        # 3. Who are the top creators?
        top_creators = await self.influencer_db.get_top_creators(category, min_followers=10000)
        
        # 4. What's the playbook?
        playbook = {
            "best_platforms": platform_stats,  # {platform: {win_rate, avg_engagement, avg_cac}}
            "proven_hooks": hook_analysis,     # [{hook: "...", success_rate: 0.8}, ...]
            "recommended_creators": top_creators[:20],  # Top creators to approach
            "estimated_cac": self._estimate_cac(category, successful_creatives),
            "expected_engagement_rate": self._benchmark_engagement(category),
            "content_template": self._generate_template(successful_creatives),
            "seasonal_patterns": self._analyze_seasonality(category),
        }
        
        return playbook
    
    def _analyze_platforms(self, creatives: list[SuccessfulCreative]) -> dict:
        """TikTok vs Instagram vs YouTube performance"""
    
    def _analyze_hooks(self, creatives: list[SuccessfulCreative]) -> list[dict]:
        """Which hooks drive the most engagement?"""
    
    def _estimate_cac(self, category: str, creatives: list[SuccessfulCreative]) -> float:
        """Based on successful campaigns in this category"""
    
    def _generate_template(self, creatives: list[SuccessfulCreative]) -> dict:
        """Aggregate best practices into content template"""
```

---

### Weeks 4-5: Competitor Monitoring & Influencer Database

**Competitor Monitoring** (Week 4):

```python
# backend/discovery/competitor_monitoring.py (NEW - 300 LOC)

class CompetitorMonitoring:
    def __init__(self):
        # Amazon Product Advertising API (requires auth)
        self.amazon_api = AmazonAPI(...)
        # eBay API
        self.ebay_api = eBayAPI(...)
        # AliExpress scraper (unofficial)
        self.aliexpress = AliExpressScraper()
    
    async def find_competitors(self, product_name: str) -> list[dict]:
        """
        Search Amazon, eBay, AliExpress for this product
        Return: seller, price, reviews, sales (estimated)
        """
        amazon_sellers = await self._search_amazon(product_name)
        ebay_sellers = await self._search_ebay(product_name)
        aliexpress_sellers = await self._search_aliexpress(product_name)
        
        return deduplicate_and_aggregate(amazon_sellers + ebay_sellers + aliexpress_sellers)
    
    async def get_market_saturation(self, product_name: str) -> float:
        """
        0 = no competitors, 1.0 = highly saturated
        Based on number of active sellers
        """
        competitors = await self.find_competitors(product_name)
        return min(1.0, len(competitors) / 20)  # >20 sellers = highly saturated
    
    async def track_price_history(self, product_name: str, seller_id: str) -> list[dict]:
        """
        Track price changes over time (weekly)
        Returns: [{date, price}, ...]
        """
```

**Influencer Database** (Week 5):

```python
# backend/discovery/influencer_database.py (NEW - 300 LOC)

class InfluencerDatabase:
    def __init__(self):
        # HypeAuditor API (for Instagram/TikTok metrics)
        self.hype = HypeAuditorAPI(api_key=os.getenv("HYPEAUDITOR_API_KEY"))
        # TikTok Creator API
        self.tiktok_creator_api = TikTokCreatorAPI(...)
        # Cache in database
        self.db = DuckDB("duckdb:///data/influencers.db")
    
    async def get_top_creators(self, niche: str, 
                               min_followers: int = 10000,
                               platform: str = "tiktok") -> list[dict]:
        """
        Top creators in this niche by engagement rate
        """
        if platform == "tiktok":
            creators = await self.tiktok_creator_api.search(
                keywords=[niche],
                min_followers=min_followers,
                sort_by="engagement_rate"
            )
        elif platform == "instagram":
            creators = await self.hype.search_influencers(
                keywords=[niche],
                min_followers=min_followers,
                sort_by="engagement_rate"
            )
        
        # Enrich with performance data
        enriched = []
        for creator in creators:
            performance = await self.get_creator_performance(creator["id"], platform)
            enriched.append({
                **creator,
                "recent_performance": performance,
                "estimated_rate": self._estimate_rate(creator),
            })
        
        return sorted(enriched, key=lambda x: x["engagement_rate"], reverse=True)
    
    async def get_creator_performance(self, creator_id: str, platform: str) -> list[dict]:
        """
        Historical posts from this creator + engagement metrics
        What content works for them?
        """
    
    def _estimate_rate(self, creator: dict) -> float:
        """
        Estimated CPM/CPC for partnership
        Based on followers, engagement rate, and platform rates
        """
```

---

### Weeks 5-6: Integration with Live System

**Flag-Based Activation** (Week 5):

```bash
# .env or docker-compose.yml

# Week 5: Data collection only (mock data still live)
USE_REAL_DATA=false
LOG_REAL_DATA=true
COLLECT_REAL_METRICS=true

# Week 5-6: A/B test (both paths run, compare)
USE_REAL_DATA=false
SHADOW_REAL_DATA=true  # Run real data in background, log decisions

# Week 6: Switch to real data
USE_REAL_DATA=true  # All decisions use real data
```

**Integration Points** (Week 6):

```python
# backend/execution/loop.py (MODIFY)

async def run_cycle(state: SystemState):
    if os.getenv("USE_REAL_DATA", "false").lower() == "true":
        # Use real data
        market_roas = await roas_repository.get_latest_roas(lookback_hours=24)
        trending_products = await product_repository.get_trending_products(limit=50)
        marketing_strategies = await strategy_playbook.generate_playbooks_batch()
    else:
        # Use mock data (existing)
        market_roas = _generate_mock_roas()
        trending_products = _generate_mock_products()
        marketing_strategies = _generate_mock_strategies()
    
    # Decision logic remains identical
    decisions = await decide(state, market_roas, trending_products, marketing_strategies)
    
    # Log both paths if shadow mode
    if os.getenv("SHADOW_REAL_DATA", "false").lower() == "true":
        event_store.append(
            workflow_id=state.id,
            event="cycle_comparison",
            data={
                "mock_decisions": decisions,  # What mock data led to
                "real_decisions": await decide(state, real_market_roas, ...),
            }
        )
    
    return decisions
```

---

## Critical Decision Gates

### Gate 1: Real ROAS Quality (End of Week 1)

**Question**: Is real ROAS data realistic and complete?

```python
# Validation checks
✓ ROAS distribution is bi-modal (not uniform 0.5-3.0)
✓ Mean ROAS differs from mock by >20%
✓ Have data for ≥20 products with ≥14 days history
✓ Deduplication working (deduplicated ROAS < raw ROAS)

If ANY fail: Debug before proceeding to Week 2
```

### Gate 2: Product Discovery Validation (End of Week 2)

**Question**: Are discovered products actually profitable and trending?

```python
# Validation checks
✓ Discovered products have ≥3 validation signals (Reddit mentions + Google Trends + supplier availability)
✓ ≥60% of discovered products are profitable (margin > 15%)
✓ Products come from ≥3 sources (not just Reddit)
✓ Average market saturation is <0.6

If ANY fail: Adjust discovery logic before proceeding to Week 3
```

### Gate 3: Creative Strategy Accuracy (End of Week 3)

**Question**: Do recommended strategies match historical success patterns?

```python
# Validation checks
✓ Recommended hooks have ≥70% success rate in category history
✓ Recommended creators have engagement rate >5%
✓ Estimated CAC within 20% of actual category CAC
✓ Content templates extracted from top 10% of creators

If ANY fail: Refine strategy aggregation before proceeding to Week 4
```

### Gate 4: Live Integration Validation (Week 5-6)

**Question**: Do real-data decisions outperform mock-data decisions?

```python
# A/B comparison (run both paths for 100 cycles)
- Mock decisions ROAS mean: X
- Real decisions ROAS mean: Y (should be > X)
- MAE of ROAS prediction with real data < MAE with mock data

If real data decisions are WORSE: Debug before switching flag
If performance similar: Investigate why (bad data quality?)
```

---

## Credential Checklist

Before starting implementation, obtain:

- [ ] Shopify Admin API token (scope: read_products, read_orders, read_fulfillments)
- [ ] Meta Business Account + App ID + App Secret
- [ ] TikTok Business Account + API access
- [ ] Google Trends API key (or unofficial pytrends credentials)
- [ ] Reddit API credentials (praw)
- [ ] Spocket API key (if using)
- [ ] CJ Dropshipping API key (if using)
- [ ] Printful API key (if using)
- [ ] HypeAuditor or similar influencer DB access (optional but recommended)

**Security**: Store all in AWS Secrets Manager or similar, NEVER in code/git.

---

## Success Metrics (After Wiring)

| Metric | Week 1 | Week 2 | Week 3 | Week 5-6 |
|--------|--------|--------|--------|----------|
| Real ROAS data available | ✅ | ✅ | ✅ | ✅ |
| Product discovery working | - | ✅ | ✅ | ✅ |
| Creative strategies defined | - | - | ✅ | ✅ |
| Real-data decisions > mock | - | - | - | ✅ |
| System latency <2s/cycle | ✅ | ✅ | ✅ | ✅ |
| Data quality issues <5% | - | ✅ | ✅ | ✅ |

---

## Next Immediate Steps

1. **This week**: Audit available credentials & API access
2. **Days 1-3**: Design final schemas based on available data sources
3. **Days 4-7**: Build Shopify integration (easiest starting point)
4. **Week 2**: Proceed with real ROAS ingestion

Ready to begin?
