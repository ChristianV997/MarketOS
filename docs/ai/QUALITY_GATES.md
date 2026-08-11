# MarketOS Quality Gates

| Gate | Required evidence | Blocked work |
|---|---|---|
| Source safety | Explicit read-only/network gate and no secrets in output | credentialed or public calls by default |
| Architecture | Existing events, Commerce MVP, and provider boundary reused | duplicate event/client/orchestration path |
| Tests | Focused selector output plus regression checks | untested behavior change |
| PR hygiene | readiness report, `session_finish --dry-run`, clean diff | artifacts, `.env`, raw payloads, unrelated files |
| Phase 1 | CJ read-only proof recorded | supplier mutation/new provider/Phase 2 expansion |

Use `scripts/ai/phase_gate.py` for deterministic guardrails. It is advisory
planning infrastructure, not a replacement for human approval.
