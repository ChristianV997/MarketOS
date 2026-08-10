import pytest
from backend.events.adapters.supabase import SupabaseEventRepositoryError
from backend.events.adapters.supabase_staging import assert_supabase_staging_allowed, explain_supabase_staging_readiness, is_supabase_staging_configured

def test_staging_requires_gate_and_server_configuration():
    env = {"SUPABASE_URL": "https://example.test", "SUPABASE_SERVICE_ROLE_KEY": "secret", "MARKETOS_SUPABASE_CANONICAL_EVENTS": "0"}
    assert not is_supabase_staging_configured(env)
    with pytest.raises(SupabaseEventRepositoryError): assert_supabase_staging_allowed({"dry_run": True, "advisory": True}, env)
    env["MARKETOS_SUPABASE_CANONICAL_EVENTS"] = "1"
    assert explain_supabase_staging_readiness(env)["configured"]
