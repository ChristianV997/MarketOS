"""services.customer_intelligence — ICP, segmentation, lead/publicity
strategy, and vertical playbooks."""
from .icp import generate_customer_segments, generate_icp
from .lead_strategy import build_lead_strategy
from .publicity_plan import build_publicity_strategy
from .report import render_customer_intelligence_markdown
from .schemas import VERTICALS
from .sprint import CustomerIntelligenceSprint, build_customer_intelligence_sprint
from .vertical_playbooks import build_vertical_playbook

__all__ = [
    "generate_icp",
    "generate_customer_segments",
    "build_lead_strategy",
    "build_publicity_strategy",
    "build_vertical_playbook",
    "build_customer_intelligence_sprint",
    "render_customer_intelligence_markdown",
    "CustomerIntelligenceSprint",
    "VERTICALS",
]
