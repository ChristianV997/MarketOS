# Market Research Ingestion

The API background research runner schedules `research.sources.v1` once the
global `FF_PILLAR_A_INGESTION` flag and its cron slot are enabled.

Source flags are independent and default to off:

```text
FF_RESEARCH_SOURCE_GOOGLE_TRENDS_V1=false
FF_RESEARCH_SOURCE_REDDIT=false
FF_RESEARCH_SOURCE_MERCADOLIBRE=false
FF_RESEARCH_SOURCE_YOUTUBE=false
FF_RESEARCH_SOURCE_AMAZON_BESTSELLERS=false
FF_RESEARCH_SOURCE_TIKTOK_ORGANIC=false
```

Staging credentials are loaded from AWS Secrets Manager when
`MARKETOS_RESEARCH_SECRET_ID` is set. The secret is a JSON object containing
only allowlisted research keys such as `TIKTOK_ACCESS_TOKEN` and
`TIKTOK_ADVERTISER_ID`. Secret values are never returned by readiness APIs or
written to ingestion history. Public sources do not require credentials.

`FF_PILLAR_A_SOURCE_V1` remains a compatibility alias for Google Trends when
the newer Google flag is unset. Reddit and MercadoLibre confidence baselines
can be configured with:

```text
PILLAR_A_SOURCE_REDDIT_CONFIDENCE_BASELINE=0.5
PILLAR_A_SOURCE_MERCADOLIBRE_CONFIDENCE_BASELINE=0.5
```

The scheduler result includes a `payload` containing per-source status and
counts plus its effective concurrency policy. A source can be `succeeded`,
`partial`, `failed`, or `skipped`.
Malformed records are rejected individually and do not discard valid records
from the same source.

`competition` is nullable. `null` means the source did not expose competition
evidence; it is not interpreted as low competition. Callers that require
competition evidence must use `TrendRecordStore.findTopN(...,
require_competition=True)`.

YouTube, Amazon Best Sellers, and TikTok Organic are registered behind their
own flags. Amazon and TikTok synthetic fallback records are rejected by the
research adapters and are never persisted as market evidence. Enable each
source independently in staging before enabling it in production.

Source fetches use bounded retries for transient server, rate-limit, timeout,
and connection failures. Authentication and schema failures are not retried.
The retry budget is controlled by `RESEARCH_SOURCE_MAX_RETRIES` (default `2`)
and `RESEARCH_SOURCE_BACKOFF_BASE_SECONDS` (default `1`).

Enabled sources are fetched concurrently but persisted serially, so slow
network calls do not serialize the batch and SQLite remains safe. Control the
fan-out with `RESEARCH_SOURCE_MAX_WORKERS` (default `4`) and cap an individual
source wait with `RESEARCH_SOURCE_TIMEOUT_SECONDS` (default `30`). After
`RESEARCH_SOURCE_FAILURE_THRESHOLD` consecutive failures (default `3`), a
source is paused for `RESEARCH_SOURCE_COOLDOWN_SECONDS` (default `900`).

The opportunity view aggregates conservatively normalized topic keys across
sources. Its rank combines bounded velocity, source confidence, source
diversity, freshness, and direct competition evidence. Missing competition is
reported as unknown and receives no artificial low-competition bonus.

The background intelligence loop consumes these deduplicated opportunities,
not the raw source records. `RESEARCH_INTELLIGENCE_MAX_TOPICS` (default `20`)
and `RESEARCH_INTELLIGENCE_MAX_AGE_HOURS` (default `72`) bound downstream work.
`RESEARCH_INTELLIGENCE_MIN_SOURCES=2` is the recommended production setting
when multiple sources are enabled; it requires source corroboration before
spending enrichment capacity on a topic.

Operational history is stored in the same SQLite research database and is
available through:

```text
GET /research/ingestion/status
GET /research/ingestion/runs?limit=20
GET /research/trends/top?limit=20&require_competition=false
GET /research/opportunities?limit=20&max_age_hours=72&min_sources=1
GET /research/sources?max_age_hours=72
GET /research/sources/readiness?max_age_hours=72
```

Use `/research/sources/readiness` before enabling a source. It reports safe
credential state, feature flags, missing key names, last live evidence, record
coverage, and the deterministic three-run reliability gate. The `promotion`
section becomes `ready` only after at least two sources each have three
successful runs with at least five live records, under 10% rejection, and
fresh evidence. The endpoint does not perform a network fetch.

Prometheus metrics are exposed under `/metrics/prometheus`, including
source-level fetch, record, retry, and duration counters.
