from pathlib import Path


def test_phase1_observability_assets_are_present():
    root = Path(__file__).parents[2]
    assert (root / "backend/observability/phase1_telemetry.py").is_file()
    assert (root / "backend/observability/telemetry_sanitization.py").is_file()
    assert (root / "frontend/src/lib/analytics.ts").is_file()
    assert (root / "docs/PHASE1_OBSERVABILITY.md").is_file()
