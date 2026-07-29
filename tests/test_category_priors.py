"""Tests for backend.data.category_priors — dataset-derived category
priors, gated behind CATEGORY_PRIORS_LIVE with the seed file shipping
empty until an operator actually ingests real data."""
import pytest


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    monkeypatch.delenv("CATEGORY_PRIORS_LIVE", raising=False)


def test_flag_off_always_returns_default(monkeypatch):
    from backend.data.category_priors import category_prior
    assert category_prior("pets", "return_proxy", 0.12) == 0.12


def test_flag_on_empty_seed_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CATEGORY_PRIORS_LIVE", "true")
    from backend.data.category_priors import category_prior
    assert category_prior("pets", "return_proxy", 0.12) == 0.12


def test_committed_seed_ships_empty():
    from backend.data.category_priors import load_priors
    import backend.data.category_priors as cp_mod
    # Read directly from the real committed seed path (not the isolated
    # state override) — this is the actual shipped artifact.
    import backend.core.persistence as pers
    real_seed = pers.load_json(cp_mod._SEED_PATH, default=None)
    assert real_seed == {}


def test_flag_on_reads_state_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CATEGORY_PRIORS_LIVE", "true")
    from backend.core.persistence import save_json_atomic, state_path
    save_json_atomic(state_path("category_priors.json"),
                     {"pets": {"return_proxy": 0.08, "repeat_rate": 0.15}})

    from backend.data.category_priors import category_prior
    assert category_prior("pets", "return_proxy", 0.12) == 0.08
    assert category_prior("pets", "repeat_rate", 0.10) == 0.15
    assert category_prior("pets", "channel_affinity", None) is None
    assert category_prior("electronics", "return_proxy", 0.15) == 0.15  # unpopulated category


def test_lookup_never_raises_on_corrupt_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CATEGORY_PRIORS_LIVE", "true")
    from backend.core.persistence import state_path
    import os
    path = state_path("category_priors.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{not valid json")

    from backend.data.category_priors import category_prior
    assert category_prior("pets", "return_proxy", 0.12) == 0.12


class TestMarginCalculatorIntegration:
    def test_category_return_rate_unaffected_by_default(self, monkeypatch):
        from backend.validation.margin_calculator import category_return_rate
        assert category_return_rate("general") == 0.12

    def test_category_return_rate_uses_live_prior_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CATEGORY_PRIORS_LIVE", "true")
        from backend.core.persistence import save_json_atomic, state_path
        save_json_atomic(state_path("category_priors.json"),
                         {"pets": {"return_proxy": 0.05}})
        from backend.validation.margin_calculator import category_return_rate
        assert category_return_rate("pets") == 0.05


class TestLtvIntegration:
    def test_category_repeat_rate_prior_unaffected_by_default(self, monkeypatch):
        from backend.economics.ltv import category_repeat_rate_prior
        assert category_repeat_rate_prior("general") == 0.10

    def test_category_repeat_rate_prior_uses_live_prior_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CATEGORY_PRIORS_LIVE", "true")
        from backend.core.persistence import save_json_atomic, state_path
        save_json_atomic(state_path("category_priors.json"),
                         {"pets": {"repeat_rate": 0.22}})
        from backend.economics.ltv import category_repeat_rate_prior
        assert category_repeat_rate_prior("pets") == 0.22


class TestChannelSelectorIntegration:
    def test_category_affinity_used_when_live_and_no_brand_preference(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHANNEL_SELECT_LIVE", "true")
        monkeypatch.setenv("CATEGORY_PRIORS_LIVE", "true")
        from backend.core.persistence import save_json_atomic, state_path
        save_json_atomic(state_path("category_priors.json"),
                         {"pets": {"channel_affinity": {"tiktok": 0.8, "meta": 0.2}}})

        from backend.launch.channel_selector import select_weights
        weights = select_weights(("tiktok", "meta"), category="pets")
        assert weights == {"tiktok": pytest.approx(0.8), "meta": pytest.approx(0.2)}

    def test_brand_preference_still_wins_over_category_affinity(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHANNEL_SELECT_LIVE", "true")
        monkeypatch.setenv("CATEGORY_PRIORS_LIVE", "true")
        from backend.core.persistence import save_json_atomic, state_path
        save_json_atomic(state_path("category_priors.json"),
                         {"pets": {"channel_affinity": {"tiktok": 0.8, "meta": 0.2}}})

        class _FakeBrand:
            brand_id = "petbrand"
            category = "pets"
            channel_preferences = {"tiktok": 0.3, "meta": 0.7}

        from backend.launch.channel_selector import select_weights
        weights = select_weights(("tiktok", "meta"), brand=_FakeBrand())
        assert weights == {"tiktok": pytest.approx(0.3), "meta": pytest.approx(0.7)}
