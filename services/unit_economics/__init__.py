"""services.unit_economics — margin/break-even/ROAS diagnostic as a
sellable service (and as an internal pre-launch gate)."""
from .analyzer import run_unit_economics
from .break_even import break_even_cac, required_roas, verdict_from_margin
from .report import render_unit_economics_markdown
from .schemas import UnitEconomicsResult

__all__ = [
    "run_unit_economics",
    "break_even_cac",
    "required_roas",
    "verdict_from_margin",
    "render_unit_economics_markdown",
    "UnitEconomicsResult",
]
