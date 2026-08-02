# OSS sidecar operations

OSS integrations are optional boundaries. They are not installed into the API
image by default and no third-party source is vendored into MarketOS.

Run `python scripts/validate_oss_inventory.py` before changing the inventory.
Run `python scripts/check_oss_policy.py` to reject restricted licenses in the
commercial core and unreviewed source-copying modes.
Run `python scripts/validate_license_manifest.py` to ensure the notices and
license manifest still match the reviewed inventory. Read
`docs/oss/DEPENDENCY_POLICY.md` before changing an upstream dependency.
Pin and test each upstream release before enabling it. Record licenses,
transitive dependencies, smoke tests, and rollback notes in the inventory.
Run `python scripts/validate_oss_runtime.py --json` for a read-only local
health and dry-run boundary report.
Run `python scripts/audit_oss_readiness.py --json` before release to collect
the static acceptance evidence and list any live checks still requiring Docker,
credentials, approved domains, or legal approval. A static pass never claims a
live sidecar was launched.
Run `python scripts/benchmark_commerce_cycle.py` to verify the canonical
signal-to-feedback dry-run path stays below its configured p95 latency budget;
CI enforces a conservative 2-second p95 threshold without external sidecars.
Run `python scripts/evaluate_medusa_sidecar.py` to emit the pinned Medusa
runtime-evaluation plan. A real local evaluation is intentionally opt-in and
requires `MEDUSA_IMAGE`, `MEDUSA_DATABASE_URL`, and both `--execute` and
`--teardown`; it reports startup time, health latency, container memory, and
whether an unauthenticated negative probe is rejected.
Run `python scripts/evaluate_saleor_benchmark.py` only to benchmark the pinned
Saleor candidate against the same read-only commerce boundary. It does not add
Saleor to MarketOS: an operator must provide an isolated Compose file, a
digest-pinned `SALEOR_BENCHMARK_IMAGE`, and an internal
`SALEOR_BENCHMARK_BASE_URL`, then explicitly pass both `--execute` and
`--teardown`. The probe reads only Saleor's public `shop` GraphQL record and
reports startup, query latency, and container memory. Do not run Medusa and
Saleor as production providers together.

Run `python scripts/evaluate_<provider>_benchmark.py` for any of the
cost-aware Stack Planner adapters — `woocommerce`, `stripe_mx`,
`mercado_pago_mx`, `chatwoot`, `mautic`, `activepieces`, `hostinger`,
`posthog_backend` (see `docs/STACK_PLANNER.md`, `docs/INTEGRATION_PORTS.md`).
Unlike the Medusa/Saleor evaluators, these adapters are either pure SaaS
APIs or externally operated services with nothing for MarketOS to start or
tear down, so the shared harness in `scripts/_provider_benchmark.py`
benchmarks reachability/latency against whatever real credentials an
operator has already configured, reusing each adapter's own `health()`
method plus, where one exists, a single read-only `list_*`/`get_*`/`query_*`
method — never a mutating one. All eight default to `status="planned"`
(no adapter constructed, no credentials read) unless `--execute` is passed,
and degrade to `"unconfigured"`/`"unreachable"`/`"partial"` rather than
raising when credentials are absent, the service is unreachable, or a probe
errors.
Run `python scripts/generate_oss_sbom.py --output artifacts/oss-sbom.json`
during release preparation to capture the reviewed OSS inventory and installed
Python package versions without network access.
CI retains that SBOM, audits base and optional-agent Python requirements with
the pinned `pip-audit` scanner, and verifies OCI source/revision labels on the
production image.
When Docker is unavailable, run `python scripts/validate_oss_compose.py` for
static overlay validation; in Docker-enabled CI, also run `docker compose
config` with a reviewed pinned `MEDUSA_IMAGE`.

Use `docker-compose.oss.example.yml` only after setting a reviewed pinned
`MEDUSA_IMAGE` and database URL. Its health check gates API startup on Medusa
readiness. Keep `MEDUSA_BASE_URL` unset for the default stack. Live orders need
an approved context and idempotency key; rollback is to stop the overlay and
unset `MEDUSA_BASE_URL`.

Postiz requires a separate AGPL compliance review before commercial delivery.
Read-only analytics may be configured independently, but live publishing is
fail-closed until `POSTIZ_COMMERCIAL_APPROVED=true` is set by the review owner.
Use `docker-compose.postiz.example.yml` only after that approval: it pins the
official Postiz image by digest, keeps Postiz off a host port, disables
registration, and requires durable database/JWT settings. It is an adapter
sidecar—not vendored Postiz source. Point MarketOS at `POSTIZ_BASE_URL` and
allowlist that host with `POSTIZ_ALLOWED_HOSTS`; the adapter probes the
authenticated read-only integrations endpoint for health and still exposes
only analytics until commercial publishing is approved. Run
`python scripts/validate_postiz_compose.py` before enabling the overlay.
Browser Use and Crawl4AI remain isolated optional workers with allowlists,
approval gates, timeouts, and dry-run defaults. Enable Browser Use only through
the `browser-use-worker` service in `docker-compose.oss.example.yml`: set a
reviewed `BROWSER_USE_VERSION`, a strong private `BROWSER_USE_WORKER_TOKEN`,
and `BROWSER_USE_ALLOWED_DOMAINS`. The service is intentionally not published
on a host port. API-to-worker calls carry the full MarketOS context and require
the shared token; the worker independently rechecks its workflow, domain,
approval, idempotency, timeout, and action-trace bounds. Live Browser Use
executions also require an explicit allowlisted URL and idempotency key;
dry-run planning remains network-free. `BROWSER_USE_LOCAL_DEVELOPMENT` is a
development-only escape hatch and must remain false in deployed environments.
n8n is an internal-only automation sidecar for alerts, CRM synchronization,
approval reminders, and exports. Do not embed it, white-label it, or expose
its workflow editor as a MarketOS customer capability; keep it behind the
allowlisted adapter and use `N8N_BASE_URL` only for an approved internal
deployment. Use `docker-compose.n8n.internal.example.yml` for the private
deployment topology: it publishes no n8n host port, pins the image, requires
durable encryption/JWT secrets, and waits for n8n health before the API starts.
Set `N8N_ALLOWED_HOSTS=n8n` (or a reviewed private DNS suffix) and a separate
`N8N_WEBHOOK_TOKEN`; configure every approved n8n Webhook workflow with Header
Auth for `X-MarketOS-Automation-Token`. An `N8N_API_KEY` is optional instance
API authentication and is not a substitute for webhook authentication. Run
`python scripts/validate_n8n_internal_compose.py` before enabling the overlay.

`MARKETOS_AGENT_QA_ENABLED=true` enables the typed campaign-QA gate. It is
disabled by default; when enabled, provider unavailability or rejection marks
the creative `not_launchable` and fails closed.

Typed PydanticAI domain agents are optional and use only bounded, read-only
MarketOS semantic evidence from the existing skill registry. Install the
reviewed profile with `pip install -r requirements-oss-agents.txt`, set the
model provider configuration, and leave money-affecting execution with the
existing MarketOS approval gates. These agents never receive advertising,
payment, browser, publishing, or fulfillment credentials.

Live Crawl4AI research requires `CRAWL4AI_ALLOWED_DOMAINS` and verifies the
target site's `robots.txt`; dry-run planning does not make network requests.
The adapter emits product evidence only from a validated structured extractor
or schema.org JSON-LD `Product` object. Supplier economics require an explicit
`unit_cost`, `wholesale_price`, or `supplier_price`; a public `price` is kept
as a selling price and is never inferred to be supplier cost.
Raw live pages use a bounded Crawl4AI cache (`CRAWL4AI_RAW_CACHE_*`), while
the bridge separately caches normalized records; `MARKETOS_OSS_MAX_CONCURRENCY`
limits concurrent external research refreshes (default `4`).

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
