# Running MarketOS continuously

This is the operator's view for actually turning MarketOS on: what runs where,
which discovery connectors return real data today vs. mock, and what stays
dry-run regardless of uptime.

## Compute topology

- **PC (primary)**: runs `orchestrator/main.py`'s tick loop continuously as a
  background service — see `contrib/systemd/` (Linux) / `contrib/launchd/`
  (macOS) and `scripts/install_daemon.sh`. Inference prefers the local Ollama
  daemon (`PREFER_LOCAL_INFERENCE=true`, on by default — see
  `backend/inference/policies/routing_policy.py`), falling back to cloud
  providers only when Ollama is unavailable or over budget.
- **AWS (standby)**: `deploy/aws/` (Terraform) provisions a low-cost
  `t3.small` EC2 instance that stays paused in `_await_takeover()`
  (`orchestrator/main.py`) and only starts ticking once the PC's S3
  heartbeat (`backend/aws/heartbeat.py`) goes stale for
  `AWS_TAKEOVER_AFTER_S` (default 300s). This IaC has been written but not
  applied — see `deploy/aws/README.md` for the manual `terraform apply` +
  `.env` upload steps against your own AWS account. No state/checkpoint
  replication yet, only liveness — see that README's limitations section.
- **State**: `STATE_PATH` (DuckDB system state) and `MARKETOS_STATE_DIR`
  (JSONL event/metric/cost/error logs, atomic-JSON pattern/playbook stores)
  both default to repo-relative paths but should point at a real home
  directory (e.g. `~/marketos-data/`) for a genuine PC deployment — the
  daemon install script sets this for you.

## Discovery connectors: what's actually scanning today

`backend/discovery/registry.py`'s `discovery_registry.status_report()` is the
live, queryable source of truth (each adapter self-reports its credential
requirements and records real fetch health every cycle). The table below is
a snapshot of what that reports as of this writing:

| Connector | File | Credentials | Status once the orchestrator is ticking |
|---|---|---|---|
| Reddit | `backend/adapters/reddit_trends.py` | none | **Live** — public JSON API, no auth |
| Google Trends | `backend/adapters/youtube_trends.py` | none | **Live** — via pytrends, no auth |
| MercadoLibre | `backend/adapters/mercadolibre_trends.py` | none | **Live** — public catalog search API |
| Amazon Best Sellers | `backend/adapters/amazon_bestsellers.py` | none | `mock_fallback` — scrapes, but Amazon blocks scripted clients often enough that success isn't guaranteed run-to-run |
| TikTok organic | `backend/adapters/tiktok_organic.py` | `TIKTOK_ACCESS_TOKEN` + `TIKTOK_ADVERTISER_ID` (optional) | `mock_fallback` — real TikTok Creative Center API if credentials set, else a pytrends proxy, else mock |
| Alibaba | `backend/adapters/alibaba_trends.py` | `FIRECRAWL_API_KEY` (optional) | `mock_fallback` — real via Firecrawl-hosted browser if the key is set (Alibaba blocks plain scraping), else mock |

No new scheduler is needed to make the "Live" rows actually run continuously:
`orchestrator/main.py`'s tick loop calls `_run_signal_ingestion()` every
tick, which forces `SignalEngine.get(force_refresh=True)` — so as long as the
orchestrator is running (see Compute topology above), these connectors are
already being queried on a real cadence, not just once at startup.

**Orphaned, not wired in** (documented for a future decision, not part of
the live pipeline): `core/sensors/tiktok_client.py` (`RAPIDAPI_KEY`) and
`connectors/tiktok_connector.py` (`TIKTOK_RESEARCH_TOKEN`) are a second,
unused TikTok client pair from an earlier iteration — `backend/adapters/
tiktok_organic.py` above is the one the live pipeline actually calls.

## What stays dry-run regardless of uptime

Running continuously does not change MarketOS's money-safety posture.
Signal scanning, discovery, and creative generation run for real once the
daemon is up. Campaign launches, real ad spend, and supplier orders remain
gated behind the existing per-integration dry-run flags (`TIKTOK_DRY_RUN`,
`META_DRY_RUN`, `STORE_DRY_RUN`, `SUPPLIERS_DRY_RUN`, `ADLIB_DRY_RUN` — all
default `true`) *and* require real credentials — see the README's
"Everything is dry-run by default" section. Uptime alone never flips these.

## Ollama / local inference

- `OLLAMA_MODEL` defaults to `mistral:7b` (primary — best reasoning/creative
  balance per `backend/ollama_manager.py`'s `RECOMMENDED_MODELS` sizing
  table: ~2GB VRAM / 4GB RAM).
- `OLLAMA_AUTO_START=true` makes `InferenceRouter` construction call
  `OllamaManager.ensure_running()`, which attempts `ollama serve` if the
  daemon isn't already up — set by the daemon install script; off by default
  otherwise so tests and ad-hoc runs never spawn a subprocess unasked.
- `PREFER_LOCAL_INFERENCE=true` (default) makes `RoutingPolicy` rank the
  fallback chain cheapest-first so Ollama wins over paid cloud providers
  whenever both are available, regardless of `INFERENCE_PROVIDERS` order.

## Obsidian sync

`orchestrator/main.py`'s `_run_obsidian_sync` worker exports the latest
discovery signals, `core/content/playbook.py`'s playbooks, and the most
recent cognitive sleep-consolidation result (`backend/runtime/sleep/`) to
an Obsidian vault via `core/brain/sync.py`'s `export_to_obsidian`. It's
opt-in and a no-op until `OBSIDIAN_VAULT_PATH` is set (the daemon install
script points it at `~/marketos-data/obsidian-vault`); rate-limited to
`OBSIDIAN_SYNC_MIN_INTERVAL_S` (default 3600s) so it writes at most one new
note per category per hour rather than one per tick.
