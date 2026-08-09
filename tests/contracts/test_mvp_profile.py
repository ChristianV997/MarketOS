from __future__ import annotations

import json
from pathlib import Path

from backend.runtime.mvp_mode import PROFILE_PATH, load_mvp_profile


ROOT = Path(__file__).resolve().parents[2]


def test_mvp_profile_is_machine_readable_and_names_safe_boundaries() -> None:
    profile = load_mvp_profile()
    assert PROFILE_PATH.is_file()
    assert profile["profile_version"] == 1
    assert "public_signal_ingestion" in profile["enabled_modules"]
    assert "canonical_events" in profile["enabled_modules"]
    assert "live_ads" in profile["disabled_modules"]
    assert "launch" in profile["forbidden_actions"]
    assert "CAPITAL_POLICY_LIVE" in profile["live_commerce_flags"]
    assert set(profile["health_endpoints"]) == {"/health", "/ready"}


def test_mvp_profile_does_not_embed_secrets_or_enable_live_modules() -> None:
    raw = json.loads((ROOT / "deploy/mvp/marketos.mvp.json").read_text(encoding="utf-8"))
    text = json.dumps(raw).lower()
    assert "secret" not in text
    assert "shopify_mutation" in raw["disabled_modules"]
    assert "provider_mutations" in raw["disabled_modules"]
