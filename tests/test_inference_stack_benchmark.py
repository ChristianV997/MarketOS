from scripts.benchmark_inference_stack import benchmark


def test_inference_benchmark_is_deterministic_and_mock_only():
    report = benchmark(runs=3)
    assert report["provider"] == "mock"
    assert report["runs"] == 3
    assert report["routing"]["p95_ms"] >= 0
    assert report["completion"]["p95_ms"] >= 0
    assert report["cache_size"] == 6
