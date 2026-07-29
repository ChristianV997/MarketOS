# OSS sidecar operations

OSS integrations are optional boundaries. They are not installed into the API
image by default and no third-party source is vendored into MarketOS.

Run `python scripts/validate_oss_inventory.py` before changing the inventory.
Run `python scripts/check_oss_policy.py` to reject restricted licenses in the
commercial core and unreviewed source-copying modes.
Pin and test each upstream release before enabling it. Record licenses,
transitive dependencies, smoke tests, and rollback notes in the inventory.
Run `python scripts/validate_oss_runtime.py --json` for a read-only local
health and dry-run boundary report.
Run `python scripts/generate_oss_sbom.py --output artifacts/oss-sbom.json`
during release preparation to capture the reviewed OSS inventory and installed
Python package versions without network access.

Use `docker-compose.oss.example.yml` only after setting a reviewed pinned
`MEDUSA_IMAGE` and database URL. Its health check gates API startup on Medusa
readiness. Keep `MEDUSA_BASE_URL` unset for the default stack. Live orders need
an approved context and idempotency key; rollback is to stop the overlay and
unset `MEDUSA_BASE_URL`.

Postiz requires a separate AGPL compliance review before commercial delivery.
Browser Use and Crawl4AI remain isolated optional workers with allowlists,
approval gates, timeouts, and dry-run defaults.

`MARKETOS_AGENT_QA_ENABLED=true` enables the typed campaign-QA gate. It is
disabled by default; when enabled, provider unavailability or rejection marks
the creative `not_launchable` and fails closed.

Live Crawl4AI research requires `CRAWL4AI_ALLOWED_DOMAINS` and verifies the
target site's `robots.txt`; dry-run planning does not make network requests.

Medusa and Postiz adapters expose bounded in-process webhook deduplication.
Production webhook receivers should persist accepted event IDs in the durable
event store before acknowledging events; the adapter ledger is a first-line
replay guard, not a cross-process replacement for durable persistence.
Set `MARKETOS_WEBHOOK_DEDUP_DB` to a shared SQLite path for cross-process
deduplication; the default `:memory:` mode is intended for local/testing use.
Set `MEDUSA_WEBHOOK_SECRET` and/or `POSTIZ_WEBHOOK_SECRET` to require
constant-time HMAC verification on inbound events. Sign the canonical sorted
JSON payload with SHA-256; an optional `sha256=` prefix is accepted.

Research retries are limited by `MARKETOS_OSS_MAX_RETRIES` (default `2`) and
`MARKETOS_OSS_RETRY_BACKOFF_S` (default `0.25`). Only transport-like failures
are retried; permission, validation, and malformed-input failures fail fast.
Dry-run and live research caches are isolated so synthetic results cannot be
reused as live evidence.

## Enabling discovery

Copy the OSS variables from `.env.example`, set
`MARKETOS_OSS_DISCOVERY=true`, and provide comma-separated
`MARKETOS_RESEARCH_URLS` plus `CRAWL4AI_ALLOWED_DOMAINS`. The orchestrator only
uses OSS discovery when its normal signal batch is empty, so it cannot silently
replace established signal sources. Keep `COMMERCE_LOOP_LIVE=false` while
validating the integration path.
