# DataForSEO Read-Only Intelligence Adapter v1

This adapter is the first concrete provider-specific implementation behind the
generic Intelligence Live Read-Only Adapter Plan. It is deliberately a
fixture-backed planning and normalization layer. It does not call DataForSEO,
load credentials, install an SDK, scrape pages, or retain provider responses.

## Why DataForSEO is first

DataForSEO is a narrower first activation target than broad extraction
providers. Search, shopping, keyword, and competitor snapshots have bounded
request shapes, clear item limits, and straightforward cost caps. That makes it
appropriate for validating MarketOS' approval, credential, terms/privacy, and
output-contract gates before any live transport exists.

## Request plans and parsing

The adapter supports organic SERP, shopping, keyword-demand, competitor-SERP,
and fixture-parse request kinds. Every plan records an endpoint placeholder,
keyword batch, location/language placeholders, result caps, cost caps,
`provider_call` approval linkage, and disabled scheduling. `--live-read-only`
does not change this: it produces a fail-closed readiness report explaining
why transport is not available.

Synthetic JSON fixtures set `fixture_mode: true` and contain only bounded task
and item fields. The parser emits normalized search, shopping, and competitor
signals with provider/method, candidate/query, rank, intent score, confidence,
limitations, terms notes, privacy notes, and a report-feed flag. Input shapes
are discarded after parsing. Raw payloads, HTML, cookies, identifiers, and
secret-like fields are rejected.

Normalized signals can be converted into the existing marketplace trend,
consumer-attention, opportunity-search, and product-validation summaries.
They enrich existing reports in dry-run mode; they do not replace those
evidence systems or imply supplier proof.

## Readiness and cost controls

DataForSEO remains `dry_run_ready` at most. A future activation needs a
metadata-only credential reference, an Approval Ledger request, a configured
budget and rate cap, complete terms/privacy review, a tested output contract,
and an owner. Planning fields include per-request/run cost bands, monthly cap,
keyword/request/result/run limits, overage risk, and stop conditions for
missing approval or credentials, cap exhaustion, schema drift, privacy/terms
gaps, network attempts, and raw-payload detection.

## Future activation steps

1. Review current provider terms and privacy treatment.
2. Create or approve a secret-manager reference without placing a secret in
   the repository.
3. Approve a bounded request envelope and budget in the Approval Ledger.
4. Implement a separately reviewed transport with network and SDK tests.
5. Compare live output to the normalized fixture contract before feeding any
   client report.

Run the offline adapter with:

```text
python scripts/run_dataforseo_readonly_adapter.py --json
python scripts/run_dataforseo_readonly_adapter.py --request-kind serp_google_shopping_snapshot --keyword "mini thermal printer" --markdown
python scripts/run_dataforseo_readonly_adapter.py --feed-opportunity-context --markdown
```

Use `--output` only when a local generated report is explicitly required;
generated artifacts remain excluded from git.

## Safety boundaries

No credentials, API keys, OAuth tokens, private keys, provider calls, model
calls, vector indexing, scraping, DataForSEO requests, SDK usage, raw HTML,
raw provider payloads, external mutations, ads, publishing, orders, payments,
or customer actions occur in this version. Fixture evidence is synthetic and
is not live search proof or launch authorization.
TrustOS is the common readiness layer around any future DataForSEO activation.
The adapter's metadata-only credential, approval, budget, terms/privacy, and
output-contract checks can feed TrustOS provider controls; `dry_run_ready` is
not live authorization.
