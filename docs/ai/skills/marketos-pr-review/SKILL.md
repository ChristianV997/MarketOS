# MarketOS PR Review

Use before opening, marking ready, or merging a PR. Inspect `AGENTS.md`, open
PRs, changed names/diff, and `scripts/ai/pr_readiness_report.py`.

Allowed: source/docs/tests in the scoped branch. Forbidden: artifacts, `.env`,
credentials, raw payloads, hidden mutations. Run selected tests, session finish,
and diff check. Report scope, CI state, risks, rollback, and safety confirmation.
