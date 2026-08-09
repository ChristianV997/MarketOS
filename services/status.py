"""services.status — the 7 commercial status labels every service module's
top-level result carries, and the shared logic that computes them.

Labels (exactly as specified):
    ready_for_dry_run       — works today, no credentials/live data needed
    ready_for_internal_use  — safe to run against your own workspace today
    ready_for_client_service — safe to sell as a delivered service today
    needs_live_data         — the analysis quality depends on real data
                              this module can't fetch itself (e.g. real ad
                              spend/orders for contribution-profit math)
    needs_credentials       — a specific integration credential is missing
                              (checked via backend.workspaces.credential_scope)
    future_saas             — needs workspace/billing/auth infra beyond what
                              exists today to serve as self-serve SaaS
    future_dao              — not applicable until backend.dao_future's
                              placeholder concepts become real

This module only computes the label; it never blocks execution — every
service function still runs and returns a result, with `status` describing
how much you should trust it as a paid deliverable.
"""
from __future__ import annotations

STATUSES = (
    "ready_for_dry_run",
    "ready_for_internal_use",
    "ready_for_client_service",
    "needs_live_data",
    "needs_credentials",
    "future_saas",
    "future_dao",
)


def commercial_status(
    *,
    requires_credentials: list[str] | None = None,
    requires_live_data: bool = False,
    workspace=None,
) -> str:
    """Never raises. `requires_credentials` is a list of
    services.customer_intelligence-style integration names (e.g.
    ["shopify"]) — if any aren't configured for `workspace`, returns
    "needs_credentials". If `requires_live_data` is True (this module's
    output quality depends on real spend/order data the module itself
    can't fetch), returns "needs_live_data" once credentials are fine.
    Otherwise "ready_for_client_service" (the module's own logic is real
    and complete; nothing here is a placeholder)."""
    try:
        if requires_credentials and workspace is not None:
            from backend.workspaces.credential_scope import scope_for
            scope = scope_for(workspace)
            missing = [c for c in requires_credentials if scope.get(c, {}).get("status") != "configured"]
            if missing:
                return "needs_credentials"
        if requires_live_data:
            return "needs_live_data"
        return "ready_for_client_service"
    except Exception:
        return "ready_for_dry_run"
