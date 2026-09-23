"""Consulting Delivery Packager.

Composes existing CommercialReport, PortfolioReport, consulting engagement,
economics, market research, supplier/logistics, and marketing outputs into
bounded client deliverables.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .schemas import ConsultingEngagement
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

MAX_DELIVERABLE_BYTES = 5 * 1024 * 1024  # 5MB size limit

@dataclass
class ConsultingDeliverable:
    engagement_id: str
    workspace_id: str
    package_id: str
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps({
            "engagement_id": self.engagement_id,
            "workspace_id": self.workspace_id,
            "package_id": self.package_id,
            "payload": self.payload,
        }, indent=2)

    def to_markdown(self) -> str:
        """Render the deliverable as safe Markdown."""
        lines = [
            f"# Consulting Deliverable: {self.package_id}",
            f"**Engagement ID:** {self.engagement_id}",
            f"**Workspace ID:** {self.workspace_id}",
            "",
            "## Payload Contents",
            ""
        ]

        for key, value in self.payload.items():
            lines.append(f"### {key.title()}")
            lines.append(f"```json\n{json.dumps(value, indent=2)}\n```")
            lines.append("")

        return "\n".join(lines)

def _check_payload_size(payload: dict[str, Any]) -> None:
    size = len(json.dumps(payload).encode("utf-8"))
    if size > MAX_DELIVERABLE_BYTES:
        raise ValueError(f"Payload size {size} exceeds max {MAX_DELIVERABLE_BYTES} bytes")

def package_deliverable(
    engagement: ConsultingEngagement,
    reports: dict[str, Any],
    required_reports: tuple[str, ...] = (),
) -> ConsultingDeliverable:
    """Safely package reports into a client deliverable."""
    if not isinstance(reports, dict):
        raise ValueError("Reports must be a dictionary")

    payload: dict[str, Any] = {}

    # Allowed report types
    allowed_types = {
        "commercial",
        "portfolio",
        "economics",
        "market_research",
        "supplier",
        "logistics",
        "marketing"
    }

    # Check for missing required reports
    missing = [req for req in required_reports if req not in reports]
    if missing:
        raise ValueError(f"Missing required reports: {missing}")

    for report_type, report_data in reports.items():
        if report_type not in allowed_types:
            continue

        if not isinstance(report_data, dict):
            raise ValueError(f"Malformed dependency: {report_type}")

        # Ensure no live execution evidence escapes unless explicitly approved
        if report_data.get("live_execution") and not report_data.get("live_approved"):
            raise ValueError(f"Unapproved live evidence in {report_type}")

        payload[report_type] = report_data

    # Check for payload size
    _check_payload_size(payload)

    # Check for TrustOS leakage
    try:
        leakage = check_workspace_leakage(payload, client_safe=True)
        if leakage:
            raise ValueError(f"Workspace isolation violation: {leakage}")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Workspace isolation violation: {str(e)}")

    return ConsultingDeliverable(
        engagement_id=engagement.engagement_id,
        workspace_id=engagement.workspace_id,
        package_id=engagement.package_id,
        payload=payload,
    )
