from scripts.evaluate_posthog_backend_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "posthog_backend"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("POSTHOG_PROJECT_API_KEY", raising=False)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
