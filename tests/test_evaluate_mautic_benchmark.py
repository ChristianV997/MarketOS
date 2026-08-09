from scripts.evaluate_mautic_benchmark import benchmark


def test_default_is_planned():
    report = benchmark(False)
    assert report["status"] == "planned"
    assert report["candidate"] == "mautic"


def test_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("MAUTIC_BASE_URL", raising=False)
    monkeypatch.delenv("MAUTIC_USERNAME", raising=False)
    monkeypatch.delenv("MAUTIC_PASSWORD", raising=False)
    report = benchmark(True)
    assert report["status"] == "unconfigured"
    assert report["mutating_operations"] is False
