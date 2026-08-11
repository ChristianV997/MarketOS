# MarketOS Live Validation

Use only for an explicitly operator-gated read-only live experiment. Inspect
the runbook, adapter/preflight, harness, and evaluation docs first.

Require explicit network permission and any documented server-side credential
gate. Never bypass robots/CAPTCHA or call mutation endpoints. Store only
sanitized normalized artifacts. Run harness/evaluation and report exact status,
observed fields, source failures, reproducibility, and next operator action.
