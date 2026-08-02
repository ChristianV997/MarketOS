from scripts.evaluate_stripe_mx_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "stripe_mx"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    import backend.config as config
    monkeypatch.setattr(config, "get_credential", lambda key: None)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
