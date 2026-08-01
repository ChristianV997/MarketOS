"""Durable claim/processing ledger for canonical commerce observations."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

from backend.core.persistence import state_path
from evaluation import CampaignObservation


class FeedbackObservationLedger:
    """Persist observation claims so retries and restarts are idempotent.

    The ledger is intentionally separate from the webhook-event ledger: an
    observation can be produced by polling or an order event and has a longer
    retention/lifecycle than transport-level webhook delivery.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or state_path("feedback_observations.sqlite3")
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS feedback_observations (
                observation_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                claimed_at REAL NOT NULL,
                processed_at REAL
            )"""
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_pending_campaign "
            "ON feedback_observations(campaign_id, status)"
        )
        self._db.commit()

    def claim(self, observation: CampaignObservation) -> bool:
        """Claim an observation once; return False for any existing claim."""
        payload = json.dumps(_observation_payload(observation), sort_keys=True)
        with self._lock:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO feedback_observations "
                "(observation_id, campaign_id, status, payload, claimed_at) "
                "VALUES (?, ?, 'claimed', ?, ?)",
                (observation.observation_id, observation.campaign_id, payload, time.time()),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def mark_processed(self, observation_id: str, *, pending: bool = False) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE feedback_observations SET status = ?, processed_at = ? "
                "WHERE observation_id = ?",
                ("pending" if pending else "processed", time.time(), observation_id),
            )
            self._db.commit()

    def release(self, observation_id: str) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM feedback_observations WHERE observation_id = ? AND status = 'claimed'",
                (observation_id,),
            )
            self._db.commit()

    def pending_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM feedback_observations "
                "WHERE campaign_id = ? AND status = 'pending' ORDER BY claimed_at",
                (campaign_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def resolve_pending(self, observation_ids: list[str]) -> None:
        if not observation_ids:
            return
        with self._lock:
            self._db.executemany(
                "UPDATE feedback_observations SET status = 'reconciled', processed_at = ? "
                "WHERE observation_id = ? AND status = 'pending'",
                [(time.time(), observation_id) for observation_id in observation_ids],
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _observation_payload(observation: CampaignObservation) -> dict[str, Any]:
    quality = observation.quality
    return {
        "observation_id": observation.observation_id,
        "campaign_id": observation.campaign_id,
        "product_id": observation.product_id,
        "creative_id": observation.creative_id,
        "spend": observation.spend,
        "revenue": observation.revenue,
        "impressions": observation.impressions,
        "clicks": observation.clicks,
        "conversions": observation.conversions,
        "refunds": observation.refunds,
        "currency": observation.currency,
        "quality": {
            "provenance": quality.provenance,
            "attribution": quality.attribution,
            "completeness": quality.completeness,
            "observed_at": quality.observed_at.isoformat(),
            "source_ref": quality.source_ref,
        },
        "metadata": observation.metadata,
    }
