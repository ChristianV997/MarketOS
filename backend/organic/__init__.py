"""backend.organic — organic social validation layer.

The owner's funnel puts organic FIRST: products are posted organically
(via Postiz), engagement/reach is measured, and only organically-validated
winners graduate to paid ad campaigns (backend/decision/organic_gate.py,
Phase F).

Modules:
    poster      — decides what to post, generates content, publishes
    engagement  — fetches post metrics, computes engagement_rate, feeds
                  the content feedback loop
"""
from backend.organic.poster import run_organic_posting
from backend.organic.engagement import ingest_engagement

__all__ = ["run_organic_posting", "ingest_engagement"]
