from __future__ import annotations

from pathlib import Path

from backend.runtime.mvp_mode import load_mvp_profile
from scripts.mvp_readiness import build_mvp_readiness


ROOT = Path(__file__).resolve().parents[2]


def test_mvp_island_has_complete_local_deployment_contract() -> None:
    report = build_mvp_readiness({"MARKETOS_MVP_MODE": "1", "ALLOWED_ORIGINS": "http://localhost:5173"})
    assert report["files_present"]
    assert report["supabase_schema_tables"] == ["workspaces", "canonical_events", "public_signals", "artifacts", "run_envelopes", "source_readiness"]
    assert len(report["supabase_required_indexes"]) == 4
    assert report["health_endpoints"] == ["/health", "/ready"]


def test_mvp_docs_and_templates_explain_manual_advisory_boundary() -> None:
    profile = load_mvp_profile()
    text = (ROOT / "docs/MVP_ISLAND.md").read_text(encoding="utf-8").lower()
    environment = (ROOT / "deploy/mvp/.env.mvp.example").read_text(encoding="utf-8")
    assert "manual approval" in text
    assert "does not prove demand" in text
    assert "TIKTOK_DRY_RUN=true" in environment
    assert "CAPITAL_POLICY_LIVE=0" in environment
    assert "background_orchestrator_loop" in profile["disabled_modules"]
