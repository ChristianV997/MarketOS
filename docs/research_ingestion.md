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

`FF_PILLAR_A_SOURCE_V1` remains a compatibility alias for Google Trends when
the newer Google flag is unset. Reddit and MercadoLibre confidence baselines
can be configured with:

```text
PILLAR_A_SOURCE_REDDIT_CONFIDENCE_BASELINE=0.5
PILLAR_A_SOURCE_MERCADOLIBRE_CONFIDENCE_BASELINE=0.5
```

The scheduler result includes a `payload` containing per-source status and
counts. A source can be `succeeded`, `partial`, `failed`, or `skipped`.
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

Operational history is stored in the same SQLite research database and is
available through:

```text
GET /research/ingestion/status
GET /research/ingestion/runs?limit=20
GET /research/trends/top?limit=20&require_competition=false
```

Prometheus metrics are exposed under `/metrics/prometheus`, including
source-level fetch, record, retry, and duration counters.
