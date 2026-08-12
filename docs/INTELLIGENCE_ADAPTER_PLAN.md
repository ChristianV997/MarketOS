# Intelligence Live Read-Only Adapter Plan v1

This is the contract layer between MarketOS' offline intelligence reports and
future provider activation. It does not call Apify, DataForSEO, SerpApi,
official APIs, or proxy providers. It does not install SDKs, load credentials,
scrape pages, run actors, or persist provider responses.

## Why planning comes first

The existing marketplace, supplier, and consumer-attention modules already
produce normalized evidence. A live adapter needs a bounded request envelope,
an output contract, a cost/rate cap, an owner, a secret-manager reference, an
Approval Ledger request, terms/privacy review, and deterministic output tests
before it is safe to implement. This module records those prerequisites.

Every contract defaults to `dry_run_request_plan`, `manual_import`, or
`blocked`. `approved_live_read_only_later` is a roadmap mode, never an active
execution mode. Bright Data and Oxylabs remain blocked because proxy-backed
acquisition has higher legal, privacy, terms, and cost risk.

## Provider request plans

- **Apify:** broad public marketplace, review, creative, and social snapshots;
  actor ID, input schema, item cap, cost cap, dataset contract, and disabled
  schedule are placeholders only.
- **DataForSEO:** search/SERP/keyword and shopping snapshots; endpoint,
  keyword batch, location, language, request cap, and cost cap are placeholders.
- **SerpApi:** bounded SERP and shopping backup; engine, query, location, and
  request limits are placeholders.
- **Official APIs:** marketplace and social/search validation is a later,
  compliance-first path.
- **Manual imports:** the current safe path for sanitized JSON/CSV evidence.

## Readiness gates

Each provider is checked for:

- a metadata-only credential reference;
- secret absence;
- a budget cap and rate limit;
- Approval Ledger request types;
- Tool Registry category;
- terms and privacy review;
- tested sanitized output contract;
- a deterministic dry-run fixture;
- explicit live-mode blocking.

Missing approval, credentials, terms/privacy review, output tests, or budget
caps are blockers. A dry-run-ready provider is not live-ready and does not
prove demand, supplier feasibility, or launch authorization.

## Evidence normalization

Provider-shaped records are reduced to normalized intermediate records with a
provider, method, placeholder source reference, capture placeholder,
normalized fields, confidence, limitations, terms notes, privacy notes,
evidence category, and report-feed flag. Raw payloads, HTML, cookies,
authorization headers, and personal data are rejected or discarded.

Mappings feed the existing `MarketplaceTrendEvidence`,
`SupplierFeasibilityEvidence`, `ConsumerAttentionEvidence`, search/review
signals, competitor pricing, creative signals, and provider-run evidence. No
second evidence engine is introduced.

## Cost and rate limits

Plans include per-run and monthly bands, maximum items, maximum runs per day,
rate-limit notes, overage risk, and stop conditions. Stop immediately when a
cap is reached, approval or terms review is missing, a credential is missing,
the schema changes, a provider errors, or privacy risk appears.

## Commands

```powershell
python scripts/run_intelligence_adapter_plan.py --json
python scripts/run_intelligence_adapter_plan.py --markdown
python scripts/run_intelligence_adapter_plan.py --provider apify --markdown
python scripts/run_intelligence_adapter_plan.py --provider dataforseo --markdown
python scripts/run_intelligence_adapter_plan.py --provider serpapi --markdown
python scripts/run_intelligence_adapter_plan.py --data-need search_serp_keyword_demand --markdown
python scripts/run_intelligence_adapter_plan.py --data-need marketplace_demand --markdown
python scripts/run_intelligence_adapter_plan.py --output artifacts/intelligence_adapter_plan/latest --markdown
```

With `--output`, only sanitized contracts, plans, checks, mappings,
normalization rules, dry-run results, and blocked-provider lists are written.
Generated artifacts must not be committed.

## Next activation sequence

Keep manual fixtures as the production-safe path. When a real workload exists,
choose one provider, assign an owner, configure only a platform secret
reference, set a cap, review terms/privacy, create an Approval Ledger request,
run the output-contract tests, and obtain explicit human approval. Only a
separate future change may add a read-only network adapter.

## Safety boundary

No credentials, API keys, OAuth tokens, private keys, provider calls, model
calls, vector indexing, scraping, actor runs, SDKs, raw provider payloads,
HTML, external mutations, or live network calls occur in this release.
