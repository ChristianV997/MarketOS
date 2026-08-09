"""backend.ledger.report — render a LedgerSnapshot as markdown, using the
shared services.reporting renderer rather than a second templating path.
"""
from __future__ import annotations

from .projections import LedgerSnapshot


def render_ledger_markdown(snapshot: LedgerSnapshot) -> str:
    from services.reporting import render_markdown_report

    d = snapshot.to_dict()
    sections = [
        {"heading": "Summary", "body": {
            "workspace_id": d["workspace_id"],
            "order_count": d["order_count"],
            "canceled_order_count": d["canceled_order_count"],
            "recognized_revenue": d["recognized_revenue"],
            "cash_collected": d["cash_collected"],
            "gross_profit": d["gross_profit"],
            "contribution_profit": d["contribution_profit"],
            "contribution_margin": d["contribution_margin"],
        }},
        {"heading": "Acquisition cost", "body": {
            "cac_blended": d["cac_blended"],
            "cac_by_channel": d["cac_by_channel"],
        }},
        {"heading": "Profit breakdown", "body": {
            "profit_per_order": d["profit_per_order"],
            "profit_per_product": d["profit_per_product"],
            "profit_per_channel": d["profit_per_channel"],
        }},
        {"heading": "Cash cycle", "body": {
            "cash_conversion_cycle_days": d["cash_conversion_cycle_days"],
        }},
    ]
    return render_markdown_report(
        f"Commerce ledger — {d['workspace_id']}", sections, dry_run=False, generated_at=d["generated_at"],
    )
