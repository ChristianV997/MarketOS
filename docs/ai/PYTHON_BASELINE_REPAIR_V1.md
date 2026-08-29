# Python Baseline Repair v1

Status: bounded baseline repair for local supervised development.

## Supported runtime

CPython 3.12 is the supported runtime for the repository. The version is
declared by `.python-version`, both Docker images, and the CI setup. Install
the declared runtime and development dependencies before running the suite:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

The optional typed-agent profile remains separate:

```powershell
python -m pip install -r requirements-oss-agents.txt
```

## Dependency classification

The base requirements declare `prometheus-client`, `trendspyg`, and
`firecrawl-py`. A shell that has not installed `requirements.txt` can still
import the canonical API and orchestrator because optional call sites are
guarded, but tests that explicitly exercise those adapters require the
declared packages. Missing packages in that unprovisioned shell are
environment-only failures, not a reason to weaken import boundaries or skip
real tests.

The SBOM assertion tracks the current reviewed `pydantic-ai==2.27.0` entry in
`requirements-oss-agents.txt`. It must be updated with the dependency bump,
not silently made version-agnostic.

## Reproduced baseline

On the clean current-main repair worktree, collection completed with 6,874
tests and zero collection errors. The full serial run completed with 6,858
passed, 11 skipped, and 7 failed. The remaining failures were the stale SBOM
expectation, absent declared packages in the local shell, and unrelated
runtime test defects; they are not evidence that import collection failed.

The repository-native local quality gate remained clear and offline. It does
not claim that the full test suite or Phase 1 readiness is green.
