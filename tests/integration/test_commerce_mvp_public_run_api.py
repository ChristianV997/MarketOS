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


def test_supplier_evidence_flag_ignored_without_server_gate(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    monkeypatch.delenv("MARKETOS_SUPPLIER_EVIDENCE_LIVE", raising=False)
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "event_count": 0, "warnings": [], "blockers": []})

    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", _fake)
    request = commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker", allow_public_network=True, attempt_supplier_evidence=True)
    report = commerce_mvp.public_run(request)
    assert captured["attempt_supplier_evidence"] is False
    assert report["supplier_evidence_attempted"] is False


def test_supplier_evidence_flag_propagates_when_server_gate_and_request_both_set(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    monkeypatch.setenv("MARKETOS_SUPPLIER_EVIDENCE_LIVE", "1")
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "event_count": 0, "warnings": [], "blockers": []})

    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", _fake)
    request = commerce_mvp.PublicCommerceRunRequest(
        query="portable espresso maker", allow_public_network=True, attempt_supplier_evidence=True,
        supplier_candidate_urls=["https://www.cjdropshipping.com/product/x.html"],
    )
    report = commerce_mvp.public_run(request)
    assert captured["attempt_supplier_evidence"] is True
    assert captured["supplier_candidate_urls"] == ["https://www.cjdropshipping.com/product/x.html"]
    assert report["supplier_evidence_attempted"] is True


def test_opportunity_ranking_flag_propagates_and_reported(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "event_count": 0, "warnings": [], "blockers": []})

    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", _fake)
    request = commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker", allow_public_network=True, use_opportunity_ranking=True)
    report = commerce_mvp.public_run(request)
    assert captured["use_opportunity_ranking"] is True
    assert report["opportunity_ranking_used"] is True


def test_opportunity_ranking_defaults_to_false(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "event_count": 0, "warnings": [], "blockers": []})

    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", _fake)
    report = commerce_mvp.public_run(commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker", allow_public_network=True))
    assert captured["use_opportunity_ranking"] is False
    assert report["opportunity_ranking_used"] is False


def test_competition_evidence_flag_ignored_without_server_gate(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    monkeypatch.delenv("MARKETOS_COMPETITION_EVIDENCE_LIVE", raising=False)
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "event_count": 0, "warnings": [], "blockers": []})

    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", _fake)
    request = commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker", allow_public_network=True, attempt_competition_evidence=True)
    report = commerce_mvp.public_run(request)
    assert captured["attempt_competition_evidence"] is False
    assert report["competition_evidence_attempted"] is False


def test_competition_evidence_flag_propagates_when_server_gate_and_request_both_set(monkeypatch):
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    monkeypatch.setenv("MARKETOS_COMPETITION_EVIDENCE_LIVE", "1")
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="succeeded", events=(), to_dict=lambda: {"public_source_status": "succeeded", "event_count": 0, "warnings": [], "blockers": []})

    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", _fake)
    request = commerce_mvp.PublicCommerceRunRequest(
        query="portable espresso maker", allow_public_network=True, attempt_competition_evidence=True,
        competitor_urls=["https://example.com/product/x"],
    )
    report = commerce_mvp.public_run(request)
    assert captured["attempt_competition_evidence"] is True
    assert captured["competitor_urls"] == ["https://example.com/product/x"]
    assert report["competition_evidence_attempted"] is True
