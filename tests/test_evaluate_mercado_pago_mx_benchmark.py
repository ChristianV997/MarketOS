from scripts.evaluate_mercado_pago_mx_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "mercado_pago_mx"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("MERCADOPAGO_ACCESS_TOKEN", raising=False)
    import backend.config as config
    monkeypatch.setattr(config, "get_credential", lambda key: None)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
