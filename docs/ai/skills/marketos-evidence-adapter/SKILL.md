# MarketOS Evidence Adapter

Use when extending an existing read-only evidence adapter. Inspect current
provider client, `backend/mvp_commerce/supplier_evidence.py`, canonical events,
and evaluation metrics.

Reuse the client and event spine; preserve field provenance and fail closed.
Forbidden: new provider without a phase-gate result, raw payload events,
credentials, mutation calls, invented price/shipping/inventory. Test fixture
normalization, gates, event safety, economics precedence, and evaluation.
