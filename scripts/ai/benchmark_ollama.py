"""Run a tiny, opt-in benchmark for bounded Ollama worker tasks.

The harness never sends repository files automatically. Inputs are explicit
text, and the benchmark exits cleanly when Ollama or a model is unavailable.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time


TASKS = {
    "summarize": "Summarize this change in three concise bullet points: add a retry with exponential backoff around a read-only HTTP request, preserve the timeout, and emit a structured warning after the final attempt.",
    "classify": "Classify this file as one of: source, test, documentation, configuration, generated. File: tests/test_checkout.py",
    "fixture": "Draft one minimal pytest test name and assertion for a function calculate_margin() that returns a positive margin for a profitable product. Do not write code outside the test.",
}


def run_task(model: str, task: str, timeout: int) -> dict:
    prompt = TASKS[task]
    started = time.perf_counter()
    try:
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        error = (result.stderr or "").strip() or None
        return {
            "task": task,
            "model": model,
            "returncode": result.returncode,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "output_chars": len(result.stdout.strip()),
            "output": result.stdout.strip(),
            "error": error,
        }
    except subprocess.TimeoutExpired:
        return {
            "task": task,
            "model": model,
            "returncode": None,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "output_chars": 0,
            "output": "",
            "error": f"timed out after {timeout}s",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="explicit local Ollama model name")
    parser.add_argument("--task", choices=[*TASKS, "all"], default="all")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not shutil.which("ollama"):
        parser.error("ollama is not available on PATH")
    selected = list(TASKS) if args.task == "all" else [args.task]
    results = [run_task(args.model, task, args.timeout) for task in selected]
    report = {"model": args.model, "tasks": results, "completed": all(r["returncode"] == 0 for r in results)}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for result in results:
            status = "ok" if result["returncode"] == 0 else "failed"
            print(f"{result['task']}: {status} ({result['duration_seconds']}s, {result['output_chars']} chars)")
            if result["error"]:
                print(f"  {result['error']}")
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
