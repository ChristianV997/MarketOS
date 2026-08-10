from scripts.supabase_staging_readiness import build_readiness

def test_readiness_is_local_and_deterministic():
    report = build_readiness(environ={})
    assert report["canonical_events_table"] and not report["network_calls"] and not report["staging"]["configured"]
