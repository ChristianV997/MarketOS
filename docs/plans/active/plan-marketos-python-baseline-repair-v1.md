# MarketOS Python Baseline Repair v1

## Objective

Make the supported CPython baseline, dependency declarations, and canonical
module imports reproducible for supervised local development without changing
business behavior or hiding real test failures.

## Scope

- Align Docker Python images with the repository's CPython 3.12 baseline.
- Keep declared runtime dependencies explicit and import-guard optional paths.
- Keep the SBOM dependency assertion aligned with the current pinned profile.
- Add focused import/startup regression coverage.

## Out of scope

- Frontend tooling and browser workers.
- Provider integrations, commerce behavior, event contracts, and workflows.
- Ruff-baseline cleanup unrelated to startup or dependency declaration.
- Converting runtime or business test failures into skips.

## Verification

- compileall for the repository Python tree;
- focused import/startup and dependency-inventory tests;
- the repository-native local quality gate;
- full pytest where practical, with all remaining failures reported;
- `git diff --check` and secret scanning.

## Safety

This plan changes no credentials, external integrations, network behavior, or
runtime authorization. The worktree remains local and the PR requires human
review; no merge is performed by this task.
