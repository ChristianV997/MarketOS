"""Productized, offline consulting offer catalog and proposal composition."""

from .catalog import all_offer_definitions, get_offer_definition
from .proposal import (
    ConsultingOfferCatalogError,
    build_consulting_offer_proposal,
    render_consulting_offer_markdown,
)
from .schemas import (
    EVIDENCE_CLASSES,
    EVIDENCE_STATES,
    OFFER_IDS,
    OFFERING_KINDS,
    ComponentReportReference,
    ConsultingOfferProposal,
    ConsultingOfferRequest,
    EvidenceInput,
    OfferDefinition,
    PlanningPriceRange,
)

__all__ = [
    "ComponentReportReference",
    "ConsultingOfferCatalogError",
    "ConsultingOfferProposal",
    "ConsultingOfferRequest",
    "EVIDENCE_CLASSES",
    "EVIDENCE_STATES",
    "EvidenceInput",
    "OFFER_IDS",
    "OFFERING_KINDS",
    "OfferDefinition",
    "PlanningPriceRange",
    "all_offer_definitions",
    "build_consulting_offer_proposal",
    "get_offer_definition",
    "render_consulting_offer_markdown",
]
