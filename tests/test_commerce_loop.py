from __future__ import annotations

from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer
from backend.commerce import CommerceLoop, CreativeBundle, LaunchExecutor, OpportunityScorer
from backend.commerce.contracts import RankedOpportunity
from backend.commerce.feedback import FeedbackRecorder
from backend.commerce.launch import LaunchPlan
from backend.vector.schemas.similarity_result import SimilarityResult


LIVE_ATTRIBUTED = DataQuality(provenance="live", attribution="attributed")
SYNTHETIC = DataQuality(provenance="simulated", attribution="unattributed")


def _winner_hit(record_id: str = "hit-1", score: float = 0.91) -> SimilarityResult:
    return SimilarityResult(record_id=record_id, score=score, payload={"roas": 2.4, "hook": "Social proof wins", "angle": "social-proof"}, collection="campaigns")


def test_ranker_prefers_live_attributed_supported_product(monkeypatch):
    monkeypatch.setattr("backend.commerce.scoring.find_similar_products", lambda query, top_k=3: [_winner_hit("prod-hit", 0.88)])
    monkeypatch.setattr("backend.commerce.scoring.find_similar_campaigns", lambda query, top_k=3: [_winner_hit("camp-hit", 0.94)])

    scorer = OpportunityScorer()
    ranked = scorer.rank(
        [
            {"id": "signal-live", "product": "Alpha", "score": 0.82, "engagement": 0.9, "velocity": 0.7, "quality": LIVE_ATTRIBUTED},
            {"id": "signal-synth", "product": "Beta", "score": 0.86, "engagement": 0.9, "velocity": 0.8, "quality": SYNTHETIC},
        ],
        products={
            "Alpha": ProductCandidate("alpha", "Alpha", selling_price=100.0, quality=LIVE_ATTRIBUTED),
            "Beta": ProductCandidate("beta", "Beta", selling_price=100.0, quality=SYNTHETIC),
        },
        offers={
            "alpha": SupplierOffer("supplier-a", "alpha", unit_cost=20.0, shipping_cost=5.0, quality=LIVE_ATTRIBUTED),
        },
        top_k=2,
    )

    assert ranked[0].product_name == "Alpha"
    assert ranked[0].readiness is not None and ranked[0].readiness.launchable
    assert "live_attributed_signal" in ranked[0].reasons
    assert ranked[1].product_name == "Beta"
    assert "not_launchable" in ranked[1].reasons


def test_launch_executor_uses_injected_backend():
    calls: list[tuple[str, dict]] = []

    def create_campaign(**kwargs):
        calls.append(("campaign", kwargs))
        return {"campaign_id": "camp-123"}

    def create_ad_group(**kwargs):
        calls.append(("adgroup", kwargs))
        return {"adgroup_id": "ag-456"}

    def create_ad(**kwargs):
        calls.append(("ad", kwargs))
        return {"ad_id": "ad-789"}

    def metrics_provider(campaign_ids):
        calls.append(("metrics", {"campaign_ids": campaign_ids}))
        return ({"spend": 20.0, "revenue": 50.0, "impressions": 1000, "clicks": 100, "conversions": 10}, LIVE_ATTRIBUTED)

    executor = LaunchExecutor(
        create_campaign=create_campaign,
        create_ad_group=create_ad_group,
        create_ad=create_ad,
        metrics_provider=metrics_provider,
    )

    opportunity = RankedOpportunity(
        artifact_id="opp-1",
        product_id="alpha",
        product_name="Alpha",
        signal_id="signal-live",
        score=92.0,
        reasons=(),
        quality=LIVE_ATTRIBUTED,
        readiness=None,
    )
    bundle = CreativeBundle.from_opportunity(
        opportunity,
        script="script",
        hook="Hook",
        angle="Angle",
        headline="Headline",
        primary_text="Primary",
        cta="Shop Now",
        quality=LIVE_ATTRIBUTED,
    )

    plan, outcome = executor.execute(bundle, budget=30.0, dry_run=False)

    assert plan.campaign_id == "camp-123"
    assert plan.adgroup_id == "ag-456"
    assert plan.ad_ids == ("ad-789",)
    assert outcome.roas == 2.5
    assert calls[0][0] == "campaign"
    assert calls[-1][0] == "metrics"


def test_feedback_recorder_reconciles_outcome_into_readiness():
    class FakeCampaignMemory:
        def __init__(self):
            self.calls = []

        def index_campaign(self, **kwargs):
            self.calls.append(kwargs)
            return 1

    class FakeReinforcementMemory:
        def __init__(self):
            self.calls = []

        def record_outcome(self, **kwargs):
            self.calls.append(kwargs)

    class FakeSignalMemory:
        def __init__(self):
            self.calls = []

        def index_keyword(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return 1

    recorder = FeedbackRecorder(
        campaign_memory=FakeCampaignMemory(),
        reinforcement_memory=FakeReinforcementMemory(),
        signal_memory=FakeSignalMemory(),
    )

    opportunity = RankedOpportunity(
        artifact_id="opp-1",
        product_id="alpha",
        product_name="Alpha",
        signal_id="signal-live",
        score=92.0,
        reasons=(),
        quality=LIVE_ATTRIBUTED,
    )
    bundle = CreativeBundle.from_opportunity(
        opportunity,
        script="script",
        hook="Hook",
        angle="Angle",
        headline="Headline",
        primary_text="Primary",
        cta="Shop Now",
        quality=LIVE_ATTRIBUTED,
    )
    plan = LaunchPlan.from_bundle(bundle, budget=25.0, dry_run=False)
    plan.campaign_id = "camp-1"
    plan.adgroup_id = "ag-1"
    plan.ad_ids = ("ad-1",)
    from backend.commerce.contracts import CampaignOutcome
    outcome = CampaignOutcome.from_metrics(
        plan,
        {"spend": 25.0, "revenue": 35.0, "impressions": 500, "clicks": 50, "conversions": 5},
        quality=SYNTHETIC,
    )
    outcome.campaign_id = ""

    result = recorder.record(
        bundle,
        plan,
        outcome=outcome,
    )

    assert result["readiness"]["launchable"] is False
    assert recorder.campaign_memory.calls == []
    assert recorder.reinforcement_memory.calls
    assert recorder.signal_memory.calls


def test_live_launch_and_feedback_update_one_durable_campaign_artifact():
    from backend.contracts.registry import get_registry

    registry = get_registry()
    opportunity = RankedOpportunity(
        artifact_id="opp-lineage", product_id="lineage-product", product_name="Lineage Product",
        signal_id="lineage-signal", score=90.0, quality=LIVE_ATTRIBUTED,
    )
    bundle = CreativeBundle.from_opportunity(
        opportunity, script="script", hook="Hook", angle="Angle", headline="Headline",
        primary_text="Primary", cta="Shop Now", quality=LIVE_ATTRIBUTED,
    )
    executor = LaunchExecutor(
        create_campaign=lambda **kwargs: {"campaign_id": "campaign-lineage"},
        create_ad_group=lambda **kwargs: {"adgroup_id": "adgroup-lineage"},
        create_ad=lambda **kwargs: {"ad_id": "ad-lineage"},
        metrics_provider=lambda campaign_ids: ({"spend": 20.0, "revenue": 40.0}, LIVE_ATTRIBUTED),
    )
    plan, outcome = executor.execute(bundle, budget=20.0, dry_run=False)
    asset = registry.get("commerce-campaign:campaign-lineage")
    assert asset is not None
    assert asset.product == "Lineage Product"
    assert asset.parent_ids == [bundle.artifact_id, plan.artifact_id]

    recorder = FeedbackRecorder(
        campaign_memory=type("FakeCampaignMemory", (), {"index_campaign": lambda self, **kwargs: 1})(),
        reinforcement_memory=type("FakeReinforcementMemory", (), {"record_outcome": lambda self, **kwargs: None})(),
        signal_memory=type("FakeSignalMemory", (), {"index_keyword": lambda self, *args, **kwargs: 1})(),
    )
    recorder.record(bundle, plan, outcome)
    updated = registry.get("commerce-campaign:campaign-lineage")
    assert updated.outcome_recorded is True
    assert updated.actual_roas == 2.0


def test_unattributed_initial_metrics_do_not_close_campaign_lineage():
    from backend.contracts.registry import get_registry

    opportunity = RankedOpportunity(
        artifact_id="opp-pending", product_id="pending-product", product_name="Pending Product",
        signal_id="pending-signal", score=90.0, quality=LIVE_ATTRIBUTED,
    )
    bundle = CreativeBundle.from_opportunity(
        opportunity, script="script", hook="Hook", angle="Angle", headline="Headline",
        primary_text="Primary", cta="Shop Now", quality=LIVE_ATTRIBUTED,
    )
    executor = LaunchExecutor(
        create_campaign=lambda **kwargs: {"campaign_id": "campaign-pending"},
        create_ad_group=lambda **kwargs: {"adgroup_id": "adgroup-pending"},
        create_ad=lambda **kwargs: {"ad_id": "ad-pending"},
        metrics_provider=lambda campaign_ids: {"spend": 20.0, "revenue": 30.0},
    )
    plan, outcome = executor.execute(bundle, budget=20.0, dry_run=False)
    recorder = FeedbackRecorder(
        campaign_memory=type("FakeCampaignMemory", (), {"index_campaign": lambda self, **kwargs: 1})(),
        reinforcement_memory=type("FakeReinforcementMemory", (), {"record_outcome": lambda self, **kwargs: None})(),
        signal_memory=type("FakeSignalMemory", (), {"index_keyword": lambda self, *args, **kwargs: 1})(),
    )
    recorder.record(bundle, plan, outcome)
    asset = get_registry().get("commerce-campaign:campaign-pending")
    assert asset is not None
    assert asset.outcome_recorded is False


def test_commerce_loop_runs_end_to_end_with_injected_dependencies(monkeypatch):
    monkeypatch.setattr("backend.commerce.scoring.find_similar_products", lambda query, top_k=3: [_winner_hit("prod-hit", 0.88)])
    monkeypatch.setattr("backend.commerce.scoring.find_similar_campaigns", lambda query, top_k=3: [_winner_hit("camp-hit", 0.94)])
    monkeypatch.setattr("backend.commerce.creative.generate_creative", lambda product, angle: f"{product}:{angle}:script")

    def create_campaign(**kwargs):
        return {"campaign_id": "camp-123"}

    def create_ad_group(**kwargs):
        return {"adgroup_id": "ag-456"}

    def create_ad(**kwargs):
        return {"ad_id": "ad-789"}

    def metrics_provider(campaign_ids):
        return ({"spend": 18.0, "revenue": 45.0, "impressions": 1200, "clicks": 120, "conversions": 12}, LIVE_ATTRIBUTED)

    loop = CommerceLoop(
        scorer=OpportunityScorer(),
        launcher=LaunchExecutor(
            create_campaign=create_campaign,
            create_ad_group=create_ad_group,
            create_ad=create_ad,
            metrics_provider=metrics_provider,
        ),
        feedback=FeedbackRecorder(
            campaign_memory=type("FakeCampaignMemory", (), {"index_campaign": lambda self, **kwargs: 1})(),
            reinforcement_memory=type("FakeReinforcementMemory", (), {"record_outcome": lambda self, **kwargs: None})(),
            signal_memory=type("FakeSignalMemory", (), {"index_keyword": lambda self, *args, **kwargs: 1})(),
        ),
    )

    report = loop.run_cycle(
        signals=[
            {"id": "s1", "product": "Alpha", "score": 0.85, "engagement": 0.91, "velocity": 0.7, "quality": LIVE_ATTRIBUTED},
            {"id": "s2", "product": "Beta", "score": 0.9, "engagement": 0.88, "velocity": 0.7, "quality": SYNTHETIC},
        ],
        products={
            "Alpha": ProductCandidate("alpha", "Alpha", selling_price=100.0, quality=LIVE_ATTRIBUTED),
            "Beta": ProductCandidate("beta", "Beta", selling_price=100.0, quality=SYNTHETIC),
        },
        offers={
            "alpha": SupplierOffer("supplier-a", "alpha", unit_cost=20.0, shipping_cost=5.0, quality=LIVE_ATTRIBUTED),
        },
        dry_run=False,
        top_k=2,
        budget=25.0,
    )

    assert report.summary["signals_collected"] == 2
    assert report.summary["launchable"] == 1
    assert len(report.ranked_opportunities) == 2
    assert len(report.launch_plans) == 1
    assert len(report.outcomes) == 1
    assert report.outcomes[0].roas == 2.5


def test_loop_preserves_quality_from_json_style_product_and_offer_overrides(monkeypatch):
    monkeypatch.setattr("backend.commerce.scoring.find_similar_products", lambda query, top_k=3: [])
    monkeypatch.setattr("backend.commerce.scoring.find_similar_campaigns", lambda query, top_k=3: [])

    report = CommerceLoop().run_cycle(
        signals=[{
            "id": "cli-signal",
            "product_id": "cli-product",
            "product": "CLI Product",
            "score": 0.9,
            "engagement": 0.8,
            "velocity": 0.7,
            "quality": {"provenance": "live", "attribution": "attributed"},
        }],
        products={"cli-product": {
            "product_id": "cli-product", "name": "CLI Product", "selling_price": 60.0,
            "quality": {"provenance": "live", "attribution": "attributed"},
        }},
        offers={"cli-product": {
            "supplier_id": "cli-supplier", "product_id": "cli-product", "unit_cost": 15.0,
            "shipping_cost": 5.0, "quality": {"provenance": "live", "attribution": "attributed"},
        }},
    )

    assert report.summary["launchable"] == 1
    assert report.summary["launches"] == 1
