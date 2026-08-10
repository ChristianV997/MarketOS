from types import SimpleNamespace

from api.routes import commerce_mvp
from backend.security.rate_limit import reset_rate_limits_for_tests


def test_public_run_returns_structured_429(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    monkeypatch.setenv("MARKETOS_PUBLIC_RUN_RATE_LIMIT", "1")
    monkeypatch.setenv("MARKETOS_PUBLIC_RUN_RATE_WINDOW_SECONDS", "600")
    reset_rate_limits_for_tests()
    fake = SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "warnings": [], "blockers": []})
    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", lambda **_kwargs: fake)
    http_request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.10"), state=SimpleNamespace(marketos_request_id="req-1"))
    request = commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker", allow_public_network=True)
    assert commerce_mvp.public_run(request, http_request=http_request)["status"] == "succeeded"
    response = commerce_mvp.public_run(request, http_request=http_request)
    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert b'"mutated":false' in response.body
    reset_rate_limits_for_tests()
