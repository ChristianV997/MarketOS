from types import SimpleNamespace

from api.routes import commerce_mvp


def test_public_api_requires_server_network_gate(monkeypatch):
    monkeypatch.delenv("MARKETOS_PUBLIC_COMMERCE_RUNS", raising=False)
    request = commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker")
    report = commerce_mvp.public_run(request)
    assert report["status"] == "blocked"
    assert "MARKETOS_PUBLIC_COMMERCE_RUNS=1" in report["blockers"][0]


def test_public_api_accepts_only_fixed_source_and_returns_advisory_report(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    fake = SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "event_count": 0, "warnings": [], "blockers": []})
    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", lambda **_kwargs: fake)
    report = commerce_mvp.public_run(commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker", allow_public_network=True))
    assert report["status"] == "succeeded"
    assert report["read_only"] is True
    assert report["mutated"] is False
    assert "source_url" not in commerce_mvp.PublicCommerceRunRequest.model_fields
