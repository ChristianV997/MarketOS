from scripts.evaluate_hostinger_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "hostinger"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("HOSTINGER_API_TOKEN", raising=False)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
