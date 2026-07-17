"""backend.metrics.campaign_metrics — real campaign performance tracking.

An append-only event log of per-campaign spend / revenue / conversions.
Two write paths:

  * record_metric(...)          — called by the orchestrator metrics worker,
                                  which knows the campaign→product mapping
                                  (full attribution).
  * ingest_campaign_metrics()   — standalone pull from the ad platforms
                                  (spend only; used by the API endpoint).

Readers aggregate the log into per-campaign performance for profitability
and budget-scaling decisions.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.core.persistence import state_path

_log = logging.getLogger(__name__)

_METRICS_PATH = Path(state_path("campaign_metrics.jsonl"))


@dataclass
class CampaignMetric:
    """One observation of a campaign's performance."""
    campaign_id: str
    platform: str
    product: str
    spend_usd: float
    revenue_usd: float = 0.0
    conversions: int = 0
    clicks: int = 0
    impressions: int = 0
    roas: float = 0.0            # revenue / spend at observation time
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


def _append(metric: CampaignMetric) -> bool:
    """Append one metric row; never raises."""
    try:
        _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_METRICS_PATH, "a") as f:
            f.write(json.dumps(metric.to_dict()) + "\n")
        return True
    except Exception as exc:
        _log.error("campaign_metric_write_failed error=%s", exc)
        return False


def record_metric(
    campaign_id: str,
    platform: str,
    product: str,
    spend_usd: float,
    revenue_usd: float = 0.0,
    conversions: int = 0,
    clicks: int = 0,
    impressions: int = 0,
) -> bool:
    """Record one campaign observation with full product attribution."""
    if not campaign_id:
        return False
    roas = round(revenue_usd / spend_usd, 4) if spend_usd > 0 else 0.0
    return _append(CampaignMetric(
        campaign_id=campaign_id,
        platform=platform,
        product=product,
        spend_usd=round(float(spend_usd), 4),
        revenue_usd=round(float(revenue_usd), 4),
        conversions=int(conversions),
        clicks=int(clicks),
        impressions=int(impressions),
        roas=roas,
    ))


def ingest_campaign_metrics() -> dict[str, Any]:
    """Pull spend from the ad platforms and log it (no product attribution).

    The orchestrator path (record_metric) is richer; this exists so the
    dashboard can trigger a pull without the orchestrator running.
    """
    campaigns: list[dict] = []
    total_spend = 0.0

    try:
        from backend.integrations import meta_ads_client
        spend_data = meta_ads_client.get_ad_spend(last_n_minutes=1440)
        for c in spend_data.get("campaigns", []):
            cid = str(c.get("campaign_id", ""))
            spend = float(c.get("spend", 0.0))
            if not cid:
                continue
            record_metric(cid, "meta", product="", spend_usd=spend)
            campaigns.append({"campaign_id": cid, "platform": "meta", "spend": spend})
            total_spend += spend
    except Exception as exc:
        _log.warning("meta_metrics_ingest_failed error=%s", exc)

    return {
        "status": "ok",
        "campaigns": campaigns,
        "total_spend": round(total_spend, 2),
        "num_campaigns": len(campaigns),
        "timestamp": time.time(),
    }


def _read_rows(since_ts: float = 0.0) -> list[dict]:
    """Read raw metric rows newer than since_ts; never raises."""
    if not _METRICS_PATH.exists():
        return []
    rows = []
    try:
        with open(_METRICS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("timestamp", 0) >= since_ts:
                    rows.append(row)
    except Exception as exc:
        _log.error("campaign_metrics_read_failed error=%s", exc)
    return rows


def campaign_performance(
    lookback_days: int = 7,
    platform: Optional[str] = None,
) -> list[dict]:
    """Aggregate the metric log into per-campaign performance.

    Returns [{campaign_id, platform, product, spend, revenue, roas,
              conversions, profit, roi_pct}], best ROAS first.
    """
    since = time.time() - lookback_days * 86400
    agg: dict[str, dict] = {}

    for row in _read_rows(since):
        if platform and row.get("platform") != platform:
            continue
        cid = row.get("campaign_id", "")
        if not cid:
            continue
        c = agg.setdefault(cid, {
            "campaign_id": cid,
            "platform": row.get("platform", ""),
            "product": row.get("product", ""),
            "spend": 0.0, "revenue": 0.0, "conversions": 0, "data_points": 0,
        })
        c["spend"] += row.get("spend_usd", 0.0)
        c["revenue"] += row.get("revenue_usd", 0.0)
        c["conversions"] += row.get("conversions", 0)
        c["data_points"] += 1
        if not c["product"] and row.get("product"):
            c["product"] = row["product"]

    result = []
    for c in agg.values():
        spend, revenue = c["spend"], c["revenue"]
        roas = revenue / spend if spend > 0 else 0.0
        result.append({
            "campaign_id": c["campaign_id"],
            "platform": c["platform"],
            "product": c["product"],
            "spend": round(spend, 2),
            "revenue": round(revenue, 2),
            "roas": round(roas, 2),
            "conversions": c["conversions"],
            "profit": round(revenue - spend, 2),
            "roi_pct": round((revenue - spend) / spend * 100, 1) if spend > 0 else 0.0,
            "data_points": c["data_points"],
        })
    return sorted(result, key=lambda x: x["roas"], reverse=True)


def campaign_by_id(campaign_id: str) -> Optional[dict]:
    """Aggregate every observation for one campaign; None if unseen."""
    rows = [r for r in _read_rows() if r.get("campaign_id") == campaign_id]
    if not rows:
        return None
    spend = sum(r.get("spend_usd", 0) for r in rows)
    revenue = sum(r.get("revenue_usd", 0) for r in rows)
    return {
        "campaign_id": campaign_id,
        "platform": rows[0].get("platform", ""),
        "product": next((r["product"] for r in rows if r.get("product")), ""),
        "total_spend": round(spend, 2),
        "total_revenue": round(revenue, 2),
        "total_conversions": sum(r.get("conversions", 0) for r in rows),
        "roas": round(revenue / spend, 2) if spend > 0 else 0.0,
        "roi_pct": round((revenue - spend) / spend * 100, 1) if spend > 0 else 0.0,
        "data_points": len(rows),
        "first_seen": min(r["timestamp"] for r in rows),
        "last_seen": max(r["timestamp"] for r in rows),
    }


__all__ = [
    "CampaignMetric",
    "record_metric",
    "ingest_campaign_metrics",
    "campaign_performance",
    "campaign_by_id",
]
