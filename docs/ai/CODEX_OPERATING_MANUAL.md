# MarketOS Codex Operating Manual

## One task, one gate, one outcome

Choose one concrete task that clears the highest unblocked gate. Start with
`session_start`, current `main`, and open PR inspection. Use Codex for local
implementation, deterministic tooling, targeted tests, and PR hygiene; use
Claude only when an already-coordinated parallel research/design task benefits
from it. Never run parallel agents over the same paths.

High-quality work is additive, bounded, tested, and explicit about whether it
is fixture-tested, dry-run, integration-tested, or live-validated. It reuses
the canonical event spine and existing Commerce MVP/evaluation paths.

## Fast loop

1. `python scripts/ai/session_start.py --json`
2. `python scripts/ai/phase_gate.py --from-git --json`
3. `python scripts/ai/select_tests.py --from-git --json`
4. Make the smallest outcome-driven change.
5. Run selected tests, then `session_finish.py --dry-run` and `git diff --check`.
6. Run `pr_readiness_report.py --json`; stage explicit files; open a draft PR.

Do not use this loop to bypass a phase gate. Credentials, artifacts, raw
payloads, provider writes, and mutation authority remain outside normal runs.
