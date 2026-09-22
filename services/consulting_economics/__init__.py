"""Product-agnostic consulting and professional-service economics."""

from .service import (
    CONSULTING_ECONOMICS_SCHEMA,
    SCENARIOS,
    SERVICE_MODELS,
    ConsultingEconomicsInputError,
    ConsultingEconomicsReport,
    ConsultingEconomicsRequest,
    ScenarioResult,
    build_consulting_economics_report,
    export_client_safe_report,
    render_consulting_economics_markdown,
)

__all__ = [
    "CONSULTING_ECONOMICS_SCHEMA",
    "SCENARIOS",
    "SERVICE_MODELS",
    "ConsultingEconomicsInputError",
    "ConsultingEconomicsReport",
    "ConsultingEconomicsRequest",
    "ScenarioResult",
    "build_consulting_economics_report",
    "export_client_safe_report",
    "render_consulting_economics_markdown",
]
