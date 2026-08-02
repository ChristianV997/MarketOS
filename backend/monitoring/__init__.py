"""backend.monitoring — production deployment monitoring and alerting.

Distinct from backend.observability (surveyed for overlap during the
consolidation pass; no genuine duplication found — they solve different
problems):
  - backend.monitoring answers "is the business logic healthy?" — alerts.py's
    8 threshold checks (error bursts, spend ceilings, ROAS floors, stuck
    workflows, ...) fire to Slack/Telegram via alerting.py (already
    correctly composed, not duplicated); dashboard_integration.py/
    health_dashboard.py track agent-structure diversity and ROAS prediction
    accuracy specifically.
  - backend.observability answers "what is the cognition/event-spine system
    doing?" — Prometheus metrics, OTel-style tracing, vector/semantic/
    lineage telemetry, routed through one telemetry_router.py entry point.

No consolidation was made here; if either package grows a second copy of
the other's concern in the future, that would be the actual signal to
merge, not the current file-name similarity (alerts.py vs alerting.py is
an intra-package split, not cross-package duplication).
"""
__all__ = []
