from scripts.ai import benchmark_ollama


def test_benchmark_defines_only_bounded_tasks():
    assert set(benchmark_ollama.TASKS) == {"summarize", "classify", "fixture"}
    assert all(len(prompt) < 500 for prompt in benchmark_ollama.TASKS.values())
