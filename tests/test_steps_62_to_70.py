"""Tests for Steps 62–70.

Step 62 — Signal Pipeline (sensors, normalize, score, top10, daily job)
Step 63 — NLP + Clustering
Step 64 — Product → Persona → Landing → Simulation → Selection → Phase 2
Step 65 — Creative Generation + Ad Execution
Step 66 — Organic Content Engine
Step 67 — Content Pattern Memory + Hook Scoring
Step 68 — Organic → Ad promote bridge
Step 69 — Brain/Obsidian sync
Step 70 — Decision Logs + Playbooks
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Step 62 — signal pipeline
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_tiktok_keys(self):
        from core.sensors.normalize import normalize_tiktok
        video = {"text": "test", "views": 1000, "likes": 100, "comments": 10}
        result = normalize_tiktok(video)
        assert result["source"] == "tiktok"
        assert result["views"] == 1000
        assert result["comments"] == 10

    def test_normalize_tiktok_missing_fields(self):
        from core.sensors.normalize import normalize_tiktok
        result = normalize_tiktok({})
        assert result["views"] == 0
        assert result["text"] == ""


class TestSensorsScoring:
    def test_engagement_rate_zero_views(self):
        from core.sensors.scoring import engagement_rate
        assert engagement_rate({"views": 0, "likes": 100}) == pytest.approx(0.0)

    def test_engagement_rate_normal(self):
        from core.sensors.scoring import engagement_rate
        result = engagement_rate({"views": 1000, "likes": 80, "comments": 20})
        assert result == pytest.approx(0.1)

    def test_score_returns_float(self):
        from core.sensors.scoring import score
        s = {"views": 1_000_000, "likes": 80_000, "comments": 20_000}
        assert score(s) > 0


class TestTop10:
    def test_returns_at_most_10(self):
        from core.reports.top10 import top10
        signals = [{"score": float(i)} for i in range(20)]
        result = top10(signals)
        assert len(result) == 10

    def test_sorted_descending(self):
        from core.reports.top10 import top10
        signals = [{"score": 1.0}, {"score": 3.0}, {"score": 2.0}]
        result = top10(signals)
        assert result[0]["score"] == pytest.approx(3.0)

    def test_fewer_than_10(self):
        from core.reports.top10 import top10
        signals = [{"score": float(i)} for i in range(5)]
        assert len(top10(signals)) == 5


class TestDailyResearch:
    def test_run_returns_list(self):
        from core.jobs.daily_research import run
        # No API key → returns empty list (no crash)
        result = run()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Step 63 — NLP + Clustering
# ---------------------------------------------------------------------------


class TestExtract:
    def test_clean_text_lowercase(self):
        from core.nlp.extract import clean_text
        assert clean_text("Hello World!") == "hello world"

    def test_clean_text_removes_special_chars(self):
        from core.nlp.extract import clean_text
        assert clean_text("fix this #issue!") == "fix this issue"


class TestEmbeddings:
    def test_embed_returns_list_of_lists(self):
        from core.nlp.embeddings import embed
        result = embed(["hello world"])
        assert isinstance(result, list)
        assert isinstance(result[0], list)
        assert all(isinstance(v, float) for v in result[0])

    def test_embed_multiple_texts(self):
        from core.nlp.embeddings import embed
        result = embed(["hello", "world"])
        assert len(result) == 2

    def test_embed_empty_list(self):
        from core.nlp.embeddings import embed
        assert embed([]) == []


class TestAngles:
    def test_extract_problem_angle(self):
        from core.nlp.angles import extract_angles
        angles = extract_angles("fix this issue fast")
        assert "problem" in angles

    def test_extract_satisfaction(self):
        from core.nlp.angles import extract_angles
        assert "satisfaction" in extract_angles("this is so satisfying and clean")

    def test_no_angles(self):
        from core.nlp.angles import extract_angles
        assert extract_angles("random unrelated text xyz") == []


class TestKmeans:
    def test_cluster_returns_labels(self):
        from core.clustering.kmeans import cluster
        vectors = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.1]]
        labels = cluster(vectors, k=2)
        assert len(labels) == 3
        assert all(isinstance(l, int) for l in labels)

    def test_cluster_empty(self):
        from core.clustering.kmeans import cluster
        assert cluster([], k=2) == []

    def test_cluster_fewer_vectors_than_k(self):
        from core.clustering.kmeans import cluster
        labels = cluster([[1.0, 0.0]], k=5)
        assert len(labels) == 1


class TestGroup:
    def test_group_by_cluster(self):
        from core.clustering.group import group_by_cluster
        signals = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        labels = [0, 1, 0]
        groups = group_by_cluster(signals, labels)
        assert len(groups[0]) == 2
        assert len(groups[1]) == 1


class TestAnalyzeCluster:
    def test_analyze_returns_keys(self):
        from core.clustering.analyze import analyze_cluster
        cluster = [
            {"views": 1000, "likes": 100, "comments": 10, "text": "fix this problem"},
            {"views": 2000, "likes": 200, "comments": 20, "text": "before and after"},
        ]
        result = analyze_cluster(cluster)
        assert "size" in result
        assert "total_views" in result
        assert "avg_engagement" in result
        assert "top_angles" in result

    def test_analyze_empty(self):
        from core.clustering.analyze import analyze_cluster
        result = analyze_cluster([])
        assert result["size"] == 0


class TestNiches:
    def test_discover_sorts_by_views(self):
        from core.reports.niches import discover
        clusters = {
            0: [{"views": 1000, "likes": 50, "comments": 5, "text": "fix problem"}],
            1: [
                {"views": 5000, "likes": 400, "comments": 40, "text": "satisfying"},
                {"views": 6000, "likes": 500, "comments": 50, "text": "clean before"},
            ],
        }
        results = discover(clusters)
        assert results[0]["total_views"] > results[-1]["total_views"]


# ---------------------------------------------------------------------------
# Step 64 — Product/Persona/Landing/Simulation/Selection/Phase2
# ---------------------------------------------------------------------------


class TestProductGenerator:
    def test_generate_products(self):
        from core.product.generator import generate_products
        cluster = [
            {"text": "portable blender bottle"},
            {"text": "magnetic screen cleaner"},
            {"text": "portable blender bottle"},  # duplicate
        ]
        products = generate_products(cluster)
        assert isinstance(products, list)
        assert len(products) <= 3

    def test_empty_cluster(self):
        from core.product.generator import generate_products
        assert generate_products([]) == []


class TestPersonaGenerator:
    def test_generate_persona_keys(self):
        from core.persona.generator import generate_persona
        persona = generate_persona([], ["problem", "convenience"])
        assert "age_range" in persona
        assert "pain_points" in persona
        assert "convenience" in persona["pain_points"]


class TestLandingGenerator:
    def test_generate_landing(self):
        from core.landing.generator import generate_landing
        landing = generate_landing("Screen Cleaner", "satisfaction")
        assert "headline" in landing
        assert "sections" in landing
        assert "Screen Cleaner" in landing["headline"]


class TestEvaluator:
    def test_evaluate_keys(self):
        from core.simulation.evaluator import evaluate
        result = evaluate("product", {}, {}, {"views": 1000, "likes": 80, "comments": 20})
        assert "predicted_ctr" in result
        assert "predicted_cvr" in result
        assert "predicted_roas" in result

    def test_evaluate_zero_views(self):
        from core.simulation.evaluator import evaluate
        result = evaluate("x", {}, {}, {"views": 0})
        assert result["predicted_ctr"] == pytest.approx(0.0)


class TestSelect:
    def test_select_best_returns_highest_roas(self):
        from core.selection.select import select_best
        candidates = [
            {"predicted_roas": 1.5},
            {"predicted_roas": 3.0},
            {"predicted_roas": 2.0},
        ]
        best = select_best(candidates)
        assert best["predicted_roas"] == pytest.approx(3.0)

    def test_select_best_empty(self):
        from core.selection.select import select_best
        assert select_best([]) is None

    def test_select_viable(self):
        from core.selection.select import select_viable
        candidates = [{"predicted_roas": 1.5}, {"predicted_roas": 2.0}]
        viable = select_viable(candidates, min_roas=1.8)
        assert len(viable) == 1
        assert viable[0]["predicted_roas"] == pytest.approx(2.0)


class TestPhase2:
    def test_run_phase2_no_clusters(self):
        from core.pipeline.phase2 import run_phase2
        assert run_phase2([]) is None

    def test_run_phase2_returns_candidate(self):
        from core.pipeline.phase2 import run_phase2
        clusters = [
            {
                "signals": [{"text": "magnetic screen cleaner"}],
                "top_angles": ["satisfaction"],
                "total_views": 1_000_000,
                "avg_engagement": 0.08,
            }
        ]
        result = run_phase2(clusters)
        assert result is not None
        assert "product" in result
        assert "predicted_roas" in result


# ---------------------------------------------------------------------------
# Step 65 — Creative Generation + Ads
# ---------------------------------------------------------------------------


class TestGenerateCreatives:
    def test_returns_list(self):
        from core.creative.generator import generate_creatives
        result = generate_creatives("Screen Cleaner", "satisfaction")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_creative_keys(self):
        from core.creative.generator import generate_creatives
        result = generate_creatives("product", "problem")
        for c in result:
            assert "hook" in c
            assert "body" in c
            assert "cta" in c

    def test_unknown_angle_fallback(self):
        from core.creative.generator import generate_creatives
        result = generate_creatives("product", "unknown_angle_xyz")
        assert len(result) >= 1


class TestVideoGenerator:
    def test_returns_string(self):
        from core.creative.video import generate_video
        result = generate_video({"hook": "test", "body": "body", "cta": "cta"})
        assert isinstance(result, str)


class TestCampaignBuilder:
    def test_build_campaign_keys(self):
        from core.ads.campaign_builder import build_campaign
        campaign = build_campaign("product", ["video1.mp4"])
        assert "budget" in campaign
        assert "creatives" in campaign
        assert campaign["budget"] == pytest.approx(10.0)


class TestAdsConnectors:
    def test_tiktok_no_token(self):
        from core.ads.tiktok import create_campaign
        result = create_campaign("", {"name": "test"})
        # Either error (no requests or connection refused) — should not raise
        assert isinstance(result, dict)

    def test_meta_returns_dict(self):
        from core.ads.meta import create_ad
        result = create_ad("123", "tok", {"name": "test"})
        assert isinstance(result, dict)

    def test_google_stub(self):
        from core.ads.google import create_campaign
        result = create_campaign(client=None)
        assert result == {"status": "stub"}


class TestPipelineExecution:
    def test_execute_dry_run(self, monkeypatch):
        import os
        from core.pipeline.execution import execute
        monkeypatch.delenv("TIKTOK_TOKEN", raising=False)
        result = execute({"product": "Screen Cleaner", "angle": "satisfaction"})
        assert result.get("status") == "dry_run"
        assert "campaign" in result


# ---------------------------------------------------------------------------
# Step 66 — Organic Content Engine
# ---------------------------------------------------------------------------


class TestContentGenerator:
    def test_generate_content_keys(self):
        from core.content.generator import generate_content
        content = generate_content("product", "satisfaction")
        assert "hook" in content
        assert "script" in content
        assert "cta" in content


class TestContentMetrics:
    def test_evaluate_defaults(self):
        from core.content.metrics import evaluate
        result = evaluate({})
        assert result["views"] == 0
        assert result["engagement"] == pytest.approx(0.0)


class TestContentScoring:
    def test_score_positive(self):
        from core.content.scoring import score
        result = score({"engagement": 0.08, "views": 100_000})
        assert result > 0


class TestContentSelect:
    def test_select_winners_top2(self):
        from core.content.select import select_winners
        posts = [
            {"engagement": 0.10, "views": 200_000},
            {"engagement": 0.02, "views": 10_000},
            {"engagement": 0.07, "views": 150_000},
        ]
        winners = select_winners(posts, top_n=2)
        assert len(winners) == 2
        assert winners[0]["score"] >= winners[1]["score"]

    def test_promote_to_ads_threshold(self):
        from core.content.select import promote_to_ads
        assert promote_to_ads({"views": 100_000, "engagement": 0.08}) is True
        assert promote_to_ads({"views": 10_000, "engagement": 0.08}) is False
        assert promote_to_ads({"views": 100_000, "engagement": 0.01}) is False


# ---------------------------------------------------------------------------
# Step 67 — Content Pattern Memory + Hook Scoring
# ---------------------------------------------------------------------------


class TestContentMemory:
    def setup_method(self):
        from core.content.memory import clear
        clear()

    def test_store_and_get(self):
        from core.content.memory import store, get_all
        store({"hook": "test", "engagement": 0.1})
        assert len(get_all()) == 1

    def test_get_all_returns_copy(self):
        from core.content.memory import store, get_all
        store({"hook": "a"})
        mem = get_all()
        mem.clear()
        assert len(get_all()) == 1


class TestContentFeatures:
    def test_extract_keys(self):
        from core.content.features import extract
        post = {"hook": "watch this", "angle": "satisfaction", "views": 5000, "engagement": 0.07}
        result = extract(post)
        assert result["hook"] == "watch this"
        assert result["views"] == 5000


class TestHookScoring:
    def test_score_zero(self):
        from core.content.hook_scoring import score
        assert score({}) == pytest.approx(0.0)

    def test_score_positive(self):
        from core.content.hook_scoring import score
        assert score({"engagement": 0.1, "views": 50_000}) > 0


class TestContentAnalytics:
    def test_analyze_aggregates(self):
        from core.content.analytics import analyze
        memory = [
            {"hook": "watch this", "angle": "satisfaction", "engagement": 0.10},
            {"hook": "watch this", "angle": "problem", "engagement": 0.06},
        ]
        result = analyze(memory)
        assert "hooks" in result
        assert "angles" in result
        assert "watch this" in result["hooks"]

    def test_analyze_empty(self):
        from core.content.analytics import analyze
        result = analyze([])
        assert result == {"hooks": {}, "angles": {}}


class TestContentOptimizer:
    def test_best_hooks(self):
        from core.content.optimizer import best_hooks
        analysis = {"hooks": {"a": 0.1, "b": 0.05, "c": 0.08}, "angles": {}}
        top = best_hooks(analysis, top_n=2)
        assert top[0][0] == "a"

    def test_best_angles(self):
        from core.content.optimizer import best_angles
        analysis = {"hooks": {}, "angles": {"satisfaction": 0.09, "problem": 0.06}}
        top = best_angles(analysis)
        assert top[0][0] == "satisfaction"


# ---------------------------------------------------------------------------
# Step 69 — Brain/Obsidian sync
# ---------------------------------------------------------------------------


class TestBrainSync:
    def test_export_and_import(self, tmp_path):
        from core.brain.sync import export_to_obsidian, import_from_obsidian
        data = {"signal": "screen cleaner", "score": 0.91}
        export_to_obsidian(data, category="signals", vault=tmp_path)
        results = import_from_obsidian(category="signals", vault=tmp_path)
        assert len(results) == 1
        assert results[0]["score"] == pytest.approx(0.91)

    def test_import_missing_vault(self, tmp_path):
        from core.brain.sync import import_from_obsidian
        results = import_from_obsidian(category="nonexistent", vault=tmp_path / "no_vault")
        assert results == []


# ---------------------------------------------------------------------------
# Step 70 — Decision Logs + Playbooks
# ---------------------------------------------------------------------------


class TestDecisionLog:
    def setup_method(self):
        from core.decision.log import clear
        clear()

    def test_log_decision(self):
        from core.decision.log import log_decision, get_all
        entry = log_decision({"roas": 2.5}, "Scale Creative A", "high engagement", "increase budget 20%")
        assert "time" in entry
        assert entry["decision"] == "Scale Creative A"
        assert len(get_all()) == 1

    def test_reason_normalised_to_list(self):
        from core.decision.log import log_decision
        entry = log_decision({}, "hold", "low signal", "no action")
        assert isinstance(entry["reason"], list)


class TestDecisionReasoning:
    def test_high_engagement(self):
        from core.decision.reasoning import explain
        reasons = explain({"engagement": 0.08}, {"ctr": 0.02, "roas": 2.5})
        assert "high engagement" in reasons
        assert "profitable" in reasons

    def test_no_signal_fallback(self):
        from core.decision.reasoning import explain
        reasons = explain({"engagement": 0.01}, {"ctr": 0.001, "roas": 0.5})
        assert "no strong signal" in reasons


class TestPlaybookGenerator:
    def test_generate_playbook_keys(self):
        from core.playbooks.generator import generate_playbook
        winner = {"niche": "cleaning tools", "angle": "satisfaction", "hook": "this is so satisfying"}
        pb = generate_playbook(winner)
        assert "niche" in pb
        assert "rules" in pb
        assert isinstance(pb["rules"], list)


class TestPlaybookStore:
    def setup_method(self):
        from core.playbooks.store import clear
        clear()

    def test_save_and_get_all(self):
        from core.playbooks.store import save, get_all
        save({"niche": "gadgets", "angle": "problem"})
        assert len(get_all()) == 1

    def test_get_all_returns_copy(self):
        from core.playbooks.store import save, get_all
        save({"niche": "cleaning"})
        pb = get_all()
        pb.clear()
        assert len(get_all()) == 1
