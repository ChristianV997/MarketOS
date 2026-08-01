from scripts.evaluate_chatwoot_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "chatwoot"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("CHATWOOT_BASE_URL", raising=False)
    monkeypatch.delenv("CHATWOOT_API_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("CHATWOOT_ACCOUNT_ID", raising=False)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
