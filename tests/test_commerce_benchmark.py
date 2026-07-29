from scripts.benchmark_commerce_cycle import benchmark


def test_commerce_dry_run_benchmark_exercises_feedback_path_within_generous_ci_budget():
    result = benchmark(runs=3, p95_limit_ms=2_000)
    assert result["within_limit"] is True
    assert result["p95_ms"] <= result["p95_limit_ms"]


def test_commerce_benchmark_restores_the_callers_inference_configuration(monkeypatch):
    monkeypatch.setenv("INFERENCE_PROVIDERS", "ollama,openai,mock")
    benchmark(runs=1, p95_limit_ms=2_000)
    assert __import__("os").environ["INFERENCE_PROVIDERS"] == "ollama,openai,mock"
