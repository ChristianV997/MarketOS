from scripts.evaluate_activepieces_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "activepieces"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("ACTIVEPIECES_BASE_URL", raising=False)
    monkeypatch.delenv("ACTIVEPIECES_API_KEY", raising=False)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
