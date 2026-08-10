from pathlib import Path


def test_phase1_hardening_assets_are_present():
    root = Path(__file__).parents[2]
    assert (root / "backend/security/cors.py").is_file()
    assert (root / "backend/security/request_context.py").is_file()
    assert (root / "backend/security/safe_logging.py").is_file()
    assert (root / "backend/security/rate_limit.py").is_file()
    assert (root / "docs/PHASE1_PRODUCTION_HARDENING.md").is_file()
