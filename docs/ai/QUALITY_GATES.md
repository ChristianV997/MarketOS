# MarketOS Quality Gates

| Gate | Required evidence | Blocked work |
|---|---|---|
| Source safety | Explicit read-only/network gate and no secrets in output | credentialed or public calls by default |
| Architecture | Existing events, Commerce MVP, and provider boundary reused | duplicate event/client/orchestration path |
| Tests | Focused selector output plus regression checks | untested behavior change |
| PR hygiene | readiness report, `session_finish --dry-run`, clean diff | artifacts, `.env`, raw payloads, unrelated files |
| Phase 1 | `phase1_readiness_report.py` records live supplier/competition evidence or its exact operator blocker | supplier mutation/new provider/Phase 2 expansion |

Use `scripts/ai/phase_gate.py` for deterministic guardrails. It is advisory
planning infrastructure, not a replacement for human approval.

Before opening a PR, run `python scripts/ai/run_local_quality_gate.py --from-git --json`.
The same local-only, advisory check runs on pull requests through
`.github/workflows/agentic-quality-gate.yml`; it writes a Markdown summary to
the GitHub job summary and never runs a live supplier or credentialed probe.

The quality-gate JSON includes the compact Phase 1 readiness score, blocking
gates, and deterministic next action. It remains useful in no-artifact mode;
missing proof is surfaced rather than fabricated.
