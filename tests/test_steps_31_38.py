"""Tests for Steps 31–38 new modules (pacing, risk, creative, ugc, memory)."""
import time
import numpy as np
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Step 31 — anomaly, drawdown
# ─────────────────────────────────────────────────────────────────────────────

class TestAnomalyDetector:
    def test_not_enough_history(self):
        from core.risk.anomaly import AnomalyDetector
        ad = AnomalyDetector()
        for v in range(5):
            ad.update(float(v))
        assert not ad.is_anomaly(999)

    def test_detects_extreme_outlier(self):
        from core.risk.anomaly import AnomalyDetector
        ad = AnomalyDetector()
        for _ in range(20):
            ad.update(1.0)
        assert ad.is_anomaly(100.0)

    def test_normal_value_not_anomaly(self):
        from core.risk.anomaly import AnomalyDetector
        ad = AnomalyDetector()
        for _ in range(20):
            ad.update(1.0)
        assert not ad.is_anomaly(1.0)


class TestDrawdownProtector:
    def test_no_stop_at_peak(self):
        from core.risk.drawdown import DrawdownProtector
        dp = DrawdownProtector()
        dp.update(100)
        assert not dp.should_stop(100)

    def test_stop_beyond_threshold(self):
        from core.risk.drawdown import DrawdownProtector
        dp = DrawdownProtector()
        dp.update(100)
        # 40% drawdown > 30% threshold
        assert dp.should_stop(60)

    def test_no_stop_within_threshold(self):
        from core.risk.drawdown import DrawdownProtector
        dp = DrawdownProtector()
        dp.update(100)
        # 20% drawdown < 30% threshold
        assert not dp.should_stop(80)

    def test_drawdown_zero_peak(self):
        from core.risk.drawdown import DrawdownProtector
        dp = DrawdownProtector()
        assert dp.drawdown(50) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Step 32 — risk rules and budget allocator
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskRules:
    def _valid_campaign(self):
        return {
            "utm_campaign": "camp1",
            "orders_clean": True,
            "spend": 25.0,
            "clicks": 60,
        }

    def test_kill_low_roas(self):
        from core.risk_rules import RiskRules
        rr = RiskRules()
        d = rr.decide(0.5, 10.0, self._valid_campaign())
        assert d.action == "kill"

    def test_hold_learning_band(self):
        from core.risk_rules import RiskRules
        rr = RiskRules()
        d = rr.decide(1.0, 10.0, self._valid_campaign())
        assert d.action == "hold"

    def test_scale_modest(self):
        from core.risk_rules import RiskRules
        rr = RiskRules()
        d = rr.decide(1.5, 10.0, self._valid_campaign())
        assert d.action == "scale"
        assert d.new_budget > 10.0

    def test_scale_elite(self):
        from core.risk_rules import RiskRules
        rr = RiskRules()
        d = rr.decide(3.0, 10.0, self._valid_campaign())
        assert d.action == "scale"
        assert d.new_budget == pytest.approx(16.0, rel=0.01)

    def test_insufficient_data_holds(self):
        from core.risk_rules import RiskRules
        rr = RiskRules()
        d = rr.decide(2.0, 10.0, {"utm_campaign": None})
        assert d.action == "hold"

    def test_drawdown_stop(self):
        from core.risk_rules import RiskRules
        rr = RiskRules()
        assert rr.should_stop_for_drawdown(60, 100)

    def test_no_drawdown_stop(self):
        from core.risk_rules import RiskRules
        rr = RiskRules()
        assert not rr.should_stop_for_drawdown(80, 100)


class TestBudgetAllocator:
    def _valid_stats(self):
        return {
            "camp1": {
                "roas": 2.0,
                "spend": 25.0,
                "clicks": 60,
                "orders_clean": True,
                "utm_campaign": "camp1",
            }
        }

    def test_scale_winner(self):
        from core.risk_rules import RiskRules
        from core.budget_allocator import BudgetAllocator
        rr = RiskRules()
        ba = BudgetAllocator(risk_rules=rr, max_daily_budget=100)
        plans = ba.allocate(self._valid_stats(), {"camp1": 10.0}, 10.0, 100, 90)
        assert plans[0].action == "scale"
        assert plans[0].new_budget > 10.0

    def test_kill_on_drawdown(self):
        from core.risk_rules import RiskRules
        from core.budget_allocator import BudgetAllocator
        rr = RiskRules()
        ba = BudgetAllocator(risk_rules=rr, max_daily_budget=100)
        plans = ba.allocate(self._valid_stats(), {"camp1": 10.0}, 10.0, 100, 50)
        assert plans[0].action == "kill"


# ─────────────────────────────────────────────────────────────────────────────
# Steps 33–34 — creative pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestCreativeGenerator:
    def test_returns_string(self):
        from core.creative.generator import generate_creative
        result = generate_creative("widget", "social-proof")
        assert isinstance(result, str) and len(result) > 0


class TestVariants:
    def test_five_variants(self):
        from core.creative.variants import generate_variants
        variants = generate_variants("widget", "direct")
        assert len(variants) == 5
        for v in variants:
            assert "angle" in v and "script" in v


class TestPrepareAssets:
    def test_prepares_correct_count(self):
        from core.creative.assets import prepare_assets
        variants = [{"angle": "a", "script": "s"}] * 3
        assets = prepare_assets(variants)
        assert len(assets) == 3
        assert all("file_path" in a and "name" in a for a in assets)



# ─────────────────────────────────────────────────────────────────────────────
# Step 35 — video generation, prompt builder, hooks, hook performance
# ─────────────────────────────────────────────────────────────────────────────

class TestVideoGenerator:
    def test_fallback_no_key(self):
        from core.creative.video_generator import generate_video
        result = generate_video("test prompt")
        assert isinstance(result, dict)
        assert "status" in result


class TestPromptBuilder:
    def test_contains_script(self):
        from core.creative.prompt_builder import script_to_prompt
        prompt = script_to_prompt("Buy this now")
        assert "Buy this now" in prompt


class TestHooks:
    def test_inject_hooks_count(self):
        from core.creative.hooks import inject_hooks, HOOKS
        variants = inject_hooks("base script")
        assert len(variants) == len(HOOKS)

    def test_hook_prepended(self):
        from core.creative.hooks import inject_hooks, HOOKS
        variants = inject_hooks("base script")
        assert variants[0].startswith(HOOKS[0])


class TestHookPerformance:
    def test_average_roas_per_hook(self):
        from core.creative.hook_performance import evaluate_hooks
        results = [
            {"hook": "h1", "roas": 2.0},
            {"hook": "h1", "roas": 4.0},
            {"hook": "h2", "roas": 1.0},
        ]
        scores = evaluate_hooks(results)
        assert scores["h1"] == pytest.approx(3.0)
        assert scores["h2"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Step 36 — templates, voiceover, compliance, account safety
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplates:
    def test_apply_template(self):
        from core.creative.templates import TEMPLATES, apply_template
        parts = {
            "hook": "Hook text",
            "problem": "Problem text",
            "solution": "Solution text",
            "cta": "CTA text",
        }
        result = apply_template(parts, TEMPLATES[0])
        assert "Hook text" in result
        assert "CTA text" in result


class TestVoiceover:
    def test_fallback_no_key(self):
        from core.creative.voiceover import generate_voice
        result = generate_voice("Hello world")
        assert isinstance(result, bytes)


class TestAvatar:
    def test_returns_dict(self):
        from core.creative.avatar import generate_avatar_video
        result = generate_avatar_video("script", b"audio")
        assert "status" in result


class TestComposer:
    def test_returns_file_path(self):
        from core.creative.composer import compose_video
        result = compose_video("script", b"audio")
        assert "file_path" in result


class TestCompliance:
    def test_valid_copy(self):
        from core.risk.compliance import validate_ad_copy
        assert validate_ad_copy("Buy this amazing product today!")

    def test_banned_copy(self):
        from core.risk.compliance import validate_ad_copy
        assert not validate_ad_copy("Guaranteed results in 24 hours!")


class TestAccountSafety:
    def test_throttle_ok(self):
        from core.risk.account_safety import throttle_launch
        assert throttle_launch(3) == "ok"

    def test_throttle_limit(self):
        from core.risk.account_safety import throttle_launch
        assert throttle_launch(10) == "limit"

    def test_warmup_new_account(self):
        from core.risk.account_safety import warmup_mode
        assert warmup_mode(3) == "low_spend"

    def test_warmup_established(self):
        from core.risk.account_safety import warmup_mode
        assert warmup_mode(30) == "normal"


# ─────────────────────────────────────────────────────────────────────────────
# Step 37 — hybrid editor, renderer
# ─────────────────────────────────────────────────────────────────────────────

class TestHybridEditor:
    def test_timeline_structure(self):
        from core.creative.hybrid_editor import build_timeline
        tl = build_timeline("Hook!", ["clip1.mp4", "clip2.mp4"], "script text")
        assert "timeline" in tl
        types = [item["type"] for item in tl["timeline"]]
        assert "text_overlay" in types
        assert "cta" in types


class TestRenderer:
    def test_returns_output_path(self):
        from core.creative.renderer import render_video
        path = render_video({"timeline": []})
        assert path == "/tmp/hybrid.mp4"


# ─────────────────────────────────────────────────────────────────────────────
# Step 38 — sequence optimizer, creative memory, embedding
# ─────────────────────────────────────────────────────────────────────────────

class TestSequenceOptimizer:
    def test_best_sequences_sorted(self):
        from core.creative.sequence_optimizer import SequenceOptimizer
        so = SequenceOptimizer()
        so.update("seq1", 1.0)
        so.update("seq2", 3.0)
        best = so.best_sequences(1)
        assert best[0][0] == "seq2"


class TestCreativeMemory:
    def test_query_returns_top_k(self):
        from core.memory.creative_memory import CreativeMemory
        mem = CreativeMemory()
        for i in range(5):
            v = np.zeros(4, dtype=np.float32)
            v[i % 4] = 1.0
            mem.add(v, {"id": i})
        query = np.array([1.0, 0, 0, 0], dtype=np.float32)
        results = mem.query(query, top_k=2)
        assert len(results) == 2

    def test_empty_memory_returns_empty(self):
        from core.memory.creative_memory import CreativeMemory
        mem = CreativeMemory()
        results = mem.query(np.array([1.0, 0], dtype=np.float32))
        assert results == []


class TestEmbedding:
    def test_returns_array(self):
        from core.creative.embedding import embed_creative
        emb = embed_creative("some ad script")
        assert isinstance(emb, np.ndarray)
        assert emb.shape == (128,)

    def test_deterministic(self):
        from core.creative.embedding import embed_creative
        e1 = embed_creative("test script")
        e2 = embed_creative("test script")
        np.testing.assert_array_equal(e1, e2)
