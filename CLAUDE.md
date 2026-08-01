# AI Development Policy

- Use the smallest sufficient context: inspect symbols and direct references before full files.
- Search for existing equivalent functionality before creating a module.
- Use architecture tools only for architecture work, current documentation tools only for external APIs, and bounded repository snapshots only for external-repository evaluation.
- Do not install MCP servers or skills globally.
- Do not enable live external actions without approval and safety gates.
- Distinguish implemented, tested, dry-run, integration-tested, and live-validated capability.
- Update repository-specific AI memory after significant architecture changes.

## Token-efficient workflow

- Read `docs/ai/CANONICAL_ARCHITECTURE.md` and `docs/ai/CANONICAL_PATHS.md` before broad discovery.
- Use `scripts/ai/check_dev_stack.py` for capability checks and `scripts/ai/generate_session_handoff.py` at session boundaries.
- Filter large test and Semgrep logs with `scripts/ai/filter_test_output.py` and `scripts/ai/filter_semgrep_output.py`.
- Use architecture/dependency tooling only for architecture work; use current external documentation only for version-sensitive APIs.
- Do not install or enable third-party MCP servers, skills, models, or plugins without review.
