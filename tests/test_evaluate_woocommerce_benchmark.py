from scripts.evaluate_woocommerce_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "woocommerce"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("WOOCOMMERCE_STORE_URL", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_SECRET", raising=False)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
