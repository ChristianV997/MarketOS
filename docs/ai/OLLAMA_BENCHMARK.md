# Ollama Benchmark

Status: installed but not recommended as a default worker. Updated: 2026-07-31.

Ollama is installed locally, but no model is currently available. The benchmark is intentionally small and bounded: three low-risk prompts, no automatic repository discovery, no secrets, and no external writes.

Validated model: `qwen2.5:0.5b`.

The three-task benchmark completed successfully, but quality was insufficient for workflow adoption: the model misclassified `tests/test_checkout.py` and generated an invalid `calculate_margin()` fixture. It is therefore retained only for experimentation with harmless summaries, never as an authority or automatic editor.

To rerun:

```powershell
python scripts/ai/benchmark_ollama.py --model <model-name> --json
```

Keep Ollama in the shared workflow only if the results show useful output with low review burden and faster turnaround than sending the same bounded task to Codex or Claude. It remains unsuitable for security, payments, authentication, scientific claims, live ads, deployments, or architectural decisions.
