# Supplier-Direct Fulfillment Risk Dry Run

This is a deterministic, offline post-purchase projection over the existing
MarketOS commerce dry-run lifecycle. It does not create an order, contact a
supplier or carrier, send a customer message, capture/refund money, write a
database, or authorize a live action.

## Authority and compatibility

The projection reuses:

- `backend.economics.kernel` for `Money`, `MarketLane`, `EvidenceRef`, and
  unit-economics/reserve calculations;
- `backend.contracts.events.Event` and `backend.events.repository` for the
  canonical event envelope, replay hashes, and idempotent local projection;
- `evaluation.commerce.dry_run_lifecycle` as the existing pre-purchase and
  order simulation authority.

The 25 post-purchase states are mapped to the existing lifecycle stages in
`LEGACY_STAGE_MAP`; this is a compatibility map, not a second event spine or
commerce order authority.

## Run a bounded report

```powershell
python scripts/run_fulfillment_risk_dry_run.py --scenario successful_direct_shipment --json
python scripts/run_fulfillment_risk_dry_run.py --scenario shipment_delayed --markdown
```

Named scenarios are sanitized fixtures. The output includes current state,
blockers, accountability and escalation routes, evidence classification, SLA
risk, reserve classifications, deterministic event hashes, and one next human
action. `live_action_allowed` is always `false`.

## Ports and evidence

`SupplierOrderPort`, `TrackingPort`, `ReturnsPort`, `WarrantyPort`, and
`SupplierCommunicationPort` are replaceable outbound ports. The included
`FixtureFulfillmentAdapter` is the only adapter supplied here and returns
bounded fixture/unavailable observations. No provider SDK, credential, network
call, raw payload, or upload is accepted by this path.

Missing responsibility routes block the report. A catalog item is not supplier
proof: an order without a `SupplierOfferIdentity` is blocked even when a
catalog identifier exists. Fixture evidence may support a dry-run report but
is classified as assumed/fixture-only and never as live validation.

Duplicate runs produce the same event IDs, payloads, and replay hashes. Passing
the events to `InMemoryEventRepository` twice produces idempotent append results.
Only a caller that explicitly supplies that local repository may append events;
the dry-run itself performs no persistence.

## Public patterns reviewed

The implementation adapts narrow, non-vendor patterns only:

- OpenLineage Facets v1.53.0: stable run identity plus bounded metadata facets;
  adapted as scenario/event correlation, evidence IDs, and deterministic
  fingerprints. No OpenLineage dependency or schema was added.
- OpenTelemetry semantic conventions v1.44.0: named, low-cardinality events
  with timestamps and structured attributes; adapted to canonical MarketOS
  event names and state attributes. No telemetry dependency was added.
- GitHub Actions REST workflow-jobs documentation (2026-03-10 API examples):
  distinguish job status/conclusion, runner identity, and executed steps;
  adapted as an explicit offline observation vocabulary. No GitHub API call is
  made by this module.
- Great Expectations Core v1.23.0: preserve validation success/failure and
  distinguish action/report output from the underlying result; adapted as
  visible `status`, `blockers`, `warnings`, and `next_human_action`. Great
  Expectations is not installed or imported.

These are documentation patterns, not copied code. Their licenses are not
introduced into MarketOS because no third-party source or dependency was added.
