# Commands

Updated: 2026-07-31

Run from the repository root:

```powershell
python scripts/ai/check_dev_stack.py --json
python scripts/ai/session_start.py --json
python scripts/ai/session_finish.py --dry-run
python scripts/ai/generate_session_handoff.py
python scripts/ai/generate_session_handoff.py --output docs/ai/SESSION_HANDOFF.md
python scripts/ai/filter_test_output.py --input test-output.txt
python scripts/ai/filter_semgrep_output.py --input semgrep-output.json
python scripts/ai/run_semgrep_policy.py
python -m pytest -q
python scripts/benchmark_inference_stack.py --runs 50 --json
python scripts/benchmark_commerce_cycle.py --runs 20 --p95-limit-ms 2000
```

Optional checks, only when installed:

```powershell
python scripts/ai/run_semgrep_policy.py --fail-on-error
python scripts/ai/verify_local_integrations.py
python scripts/ai/push_handoff_to_obsidian.py --input docs/ai/SESSION_HANDOFF.md --dry-run
uvx --from git+https://github.com/oraios/serena serena project health-check .
repomix --version
repomix backend/inference scripts/ai docs/ai --compress --no-files --stdout
```

Never put credentials or unfiltered giant logs into handoffs.

Parallel work:

```powershell
Get-Content docs/ai/PARALLEL_WORK_MATRIX.md
```

Run `session_start.py` before editing. It reports changed paths and flags
owned-path changes so Codex and Claude do not duplicate work. Run
`session_finish.py --dry-run` before committing; use it without `--dry-run`
when the session handoff should be regenerated.
