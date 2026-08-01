from pathlib import Path

from scripts.evaluate_saleor_benchmark import evaluate


def test_saleor_benchmark_is_non_mutating_by_default():
    report = evaluate()

    assert report["status"] == "planned"
    assert report["executed"] is False
    assert report["mode"] == "benchmark_only"
    assert report["mutating_operations"] is False
    assert report["commands"] == {}


def test_saleor_benchmark_requires_execution_and_teardown_together():
    assert evaluate(execute=True, teardown=False)["status"] == "blocked"
    assert evaluate(execute=False, teardown=True)["status"] == "blocked"


def test_saleor_benchmark_requires_digest_pinned_isolated_configuration(tmp_path: Path):
    compose = tmp_path / "saleor.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    missing_digest = evaluate(
        execute=True,
        teardown=True,
        compose_file=compose,
        base_url="http://127.0.0.1:8000",
        image="ghcr.io/saleor/saleor:3.23.7",
    )
    assert missing_digest["status"] == "blocked"
    assert "sha256" in str(missing_digest["reason"])


def test_saleor_benchmark_skips_without_docker_after_validation(tmp_path: Path, monkeypatch):
    compose = tmp_path / "saleor.yml"
    image = "ghcr.io/saleor/saleor:3.23.7@sha256:" + "a" * 64
    compose.write_text(f"services:\n  api:\n    image: {image}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.evaluate_saleor_benchmark.shutil.which", lambda _: None)

    report = evaluate(
        execute=True,
        teardown=True,
        compose_file=compose,
        base_url="http://127.0.0.1:8000",
        image=image,
    )

    assert report["status"] == "skipped"


def test_saleor_benchmark_rejects_a_nonmatching_or_unisolated_compose(tmp_path: Path, monkeypatch):
    image = "ghcr.io/saleor/saleor:3.23.7@sha256:" + "b" * 64
    compose = tmp_path / "saleor.yml"
    compose.write_text("services:\n  api:\n    image: ghcr.io/example/not-saleor@sha256:" + "a" * 64 + "\n", encoding="utf-8")
    monkeypatch.setattr("scripts.evaluate_saleor_benchmark.shutil.which", lambda _: None)

    report = evaluate(
        execute=True,
        teardown=True,
        compose_file=compose,
        base_url="https://untrusted.example",
        image=image,
    )

    assert report["status"] == "blocked"
    assert "isolated local" in str(report["reason"])
