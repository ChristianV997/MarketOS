"""services.creative_growth — creative/UGC/fatigue testing system as a
sellable service, wrapping the already-real core.creative/core.ugc machinery."""
from .content_calendar_report import build_content_calendar
from .fatigue_report import analyze_creative_fatigue
from .hooks import generate_ad_angles, generate_hook_matrix
from .plan import build_creative_growth_plan, recommend_next_creative_batch
from .report import render_creative_growth_markdown
from .schemas import CreativeGrowthPlan
from .ugc_plan import generate_ugc_briefs

__all__ = [
    "generate_ad_angles",
    "generate_hook_matrix",
    "generate_ugc_briefs",
    "build_content_calendar",
    "analyze_creative_fatigue",
    "recommend_next_creative_batch",
    "build_creative_growth_plan",
    "render_creative_growth_markdown",
    "CreativeGrowthPlan",
]
