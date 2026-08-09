"""backend.orchestration.transaction — coordinated cross-platform campaign launch.

``launch_product()`` in backend.launch.orchestrator launches sequentially
and keeps whatever happened to succeed. LaunchTransaction adds the missing
coordination:

  Prepare  — every requested platform must pass its circuit-breaker gate
             *before* any money moves; unhealthy platforms either fail the
             transaction (atomic) or get their budget re-allocated to the
             healthy ones (best-effort).
  Execute  — healthy platforms launch in parallel threads.
  Settle   — atomic=True: any platform failure pauses the campaigns that
             did go live (money can't be un-spent, so "rollback" for an ad
             platform means pause-immediately) and the transaction fails.
             atomic=False (default): live campaigns are kept, the partial
             outcome is journaled, and status reflects it honestly.

Every phase is journaled through the event store, so a crash mid-launch is
visible via ``event_store.incomplete_workflows()`` and the launched
campaign ids are recoverable from step_completed events for pausing or
adoption on restart.

Semantics note: best-effort is the default on purpose. For dropship ads a
live TikTok campaign is still valuable when Meta is down — strict
atomicity would convert a 1-platform outage into 0 revenue. Atomic mode
exists for flows where lopsided spend is worse than no spend.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.orchestration.event_store import event_store, new_workflow_id
from backend.orchestration.state_machine import health_registry

_log = logging.getLogger(__name__)

# Serialize transactions so two concurrent launches can't both consume the
# same remaining daily budget headroom.
_tx_lock = threading.Lock()


@dataclass
class TransactionResult:
    workflow_id: str
    status: str                    # "ok" | "partial" | "failed"
    campaigns: list[dict] = field(default_factory=list)
    compensated: list[str] = field(default_factory=list)   # paused campaign ids
    skipped_platforms: list[str] = field(default_factory=list)
    total_budget: float = 0.0


class LaunchTransaction:
    """Coordinated launch of one product across several ad platforms."""

    def __init__(self, *, atomic: bool = False,
                 launchers: dict[str, Callable] | None = None,
                 pausers: dict[str, Callable] | None = None):
        self.atomic = atomic
        self._launchers = launchers or self._default_launchers()
        self._pausers = pausers or self._default_pausers()

    # ── defaults wire to the existing launch orchestrator/clients ────────

    @staticmethod
    def _default_launchers() -> dict[str, Callable]:
        from backend.launch import orchestrator as lo

        return {
            "tiktok": lambda product, page_url, budget, copy:
                lo._launch_tiktok(product, page_url, budget, copy),
            "meta": lambda product, page_url, budget, copy:
                lo._launch_meta(product, page_url, budget, copy),
        }

    @staticmethod
    def _default_pausers() -> dict[str, Callable]:
        from backend.integrations import meta_ads_client, tiktok_ads

        return {
            "tiktok": tiktok_ads.pause_campaign,
            "meta": meta_ads_client.pause_campaign,
        }

    # ── main entry ───────────────────────────────────────────────────────

    def execute(self, build: dict[str, Any], budget_daily: float = 50.0,
                platforms: tuple[str, ...] = ("tiktok", "meta"),
                ) -> TransactionResult:
        wid = new_workflow_id("launch_tx")
        product = build.get("product", "unknown")
        page_url = (build.get("page") or {}).get("url", "")
        ad_copy = build.get("ad_copy") or {}

        with _tx_lock:
            event_store.append(wid, "workflow_started", workflow="launch_tx",
                               data={"product": product,
                                     "platforms": list(platforms),
                                     "budget_daily": budget_daily,
                                     "atomic": self.atomic})

            # ── Prepare: health-gate before any spend ────────────────────
            healthy = [p for p in platforms
                       if health_registry.get(p).allow_request()]
            skipped = [p for p in platforms if p not in healthy]

            if skipped:
                event_store.append(wid, "step_failed", workflow="launch_tx",
                                   step="prepare",
                                   data={"unhealthy_platforms": skipped})
            if not healthy or (self.atomic and skipped):
                event_store.append(wid, "workflow_failed", workflow="launch_tx",
                                   data={"reason": "platforms_unhealthy",
                                         "skipped": skipped})
                return TransactionResult(wid, "failed",
                                         skipped_platforms=skipped)

            brand = None
            try:
                from backend.commerce.brands import brand_registry
                brand = brand_registry.get(build.get("brand_id", ""))
            except Exception:
                pass
            budgets = self._allocate(budget_daily, healthy, brand=brand)
            event_store.append(wid, "step_completed", workflow="launch_tx",
                               step="prepare", data={"output": budgets})

            # ── Execute: parallel platform launches ──────────────────────
            results: dict[str, dict] = {}

            def _launch(platform: str) -> None:
                try:
                    res = self._launchers[platform](
                        product, page_url, budgets[platform],
                        ad_copy.get(platform) or {})
                except Exception as exc:
                    _log.exception("tx_launch_failed platform=%s", platform)
                    res = {"platform": platform, "status": "error",
                           "error": str(exc)}
                if not res.get("platform"):
                    res["platform"] = platform
                results[platform] = res
                event_store.append(
                    wid,
                    "step_completed" if res.get("status") == "live"
                    else "step_failed",
                    workflow="launch_tx", step=f"launch_{platform}",
                    data={"output": res})

            threads = [threading.Thread(target=_launch, args=(p,),
                                        name=f"launch-{p}")
                       for p in healthy]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=120)

            live = [r for r in results.values() if r.get("status") == "live"]
            failed = [r for r in results.values() if r.get("status") != "live"]
            campaigns = list(results.values())

            # ── Settle ───────────────────────────────────────────────────
            if failed and self.atomic and live:
                compensated = self._compensate(wid, live)
                event_store.append(wid, "workflow_failed", workflow="launch_tx",
                                   data={"reason": "partial_failure_rolled_back",
                                         "failed": [r.get("platform") for r in failed]})
                return TransactionResult(wid, "failed", campaigns=campaigns,
                                         compensated=compensated,
                                         skipped_platforms=skipped)

            if not live:
                event_store.append(wid, "workflow_failed", workflow="launch_tx",
                                   data={"reason": "all_platforms_failed"})
                return TransactionResult(wid, "failed", campaigns=campaigns,
                                         skipped_platforms=skipped)

            status = "ok" if not failed and not skipped else "partial"
            event_store.append(wid, "workflow_completed", workflow="launch_tx",
                               data={"status": status,
                                     "live": [r.get("campaign_id") for r in live]})
            return TransactionResult(
                wid, status, campaigns=campaigns, skipped_platforms=skipped,
                total_budget=round(sum(r.get("budget", 0.0) for r in live), 2))

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _allocate(budget_daily: float, platforms: list[str], brand: Any = None) -> dict[str, float]:
        """Split budget by channel_selector's preference weights,
        renormalized over the healthy set — an unhealthy platform's share
        flows to the healthy ones instead of silently evaporating."""
        from backend.launch.channel_selector import select_weights
        weights = select_weights(tuple(platforms), brand=brand)
        total = sum(weights.values()) or 1.0
        return {p: round(budget_daily * w / total, 2)
                for p, w in weights.items()}

    def _compensate(self, wid: str, live: list[dict]) -> list[str]:
        """Pause every live campaign (reverse 'rollback' for ad spend).
        A pause that itself fails is journaled, never raises."""
        paused: list[str] = []
        for res in live:
            platform = res.get("platform", "")
            cid = res.get("campaign_id", "")
            pauser = self._pausers.get(platform)
            if not pauser or not cid:
                continue
            try:
                ok = bool(pauser(cid))
            except Exception as exc:
                _log.exception("tx_compensate_failed platform=%s id=%s",
                               platform, cid)
                ok = False
                event_store.append(wid, "step_failed", workflow="launch_tx",
                                   step=f"compensate_{platform}",
                                   data={"campaign_id": cid, "error": str(exc)})
            if ok:
                paused.append(cid)
                event_store.append(wid, "step_compensated",
                                   workflow="launch_tx",
                                   step=f"compensate_{platform}",
                                   data={"campaign_id": cid})
        return paused


__all__ = ["LaunchTransaction", "TransactionResult"]
