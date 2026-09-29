"""Proves consulting_engagement consumes the canonical offer catalog from
consulting_offers (PR #317) through a real import/dependency -- it never
redefines or copies OFFER_IDS."""
from __future__ import annotations

import pytest

from services.consulting_engagement.schemas import ConsultingEngagementRequest, SchemaValidationError
from services.consulting_offers import OFFER_IDS as canonical_offer_ids
from services.consulting_engagement.schemas import OFFER_IDS as engagement_offer_ids

_BASE_KWARGS = dict(
    client_id="client-1",
    workspace_id="workspace-1",
    client_objective="Evaluate a product opportunity.",
    geography="Mexico",
    language="es-MX",
    scope="Bounded research review.",
    offering_kind="product",
)


def test_engagement_schema_imports_the_same_offer_ids_object_not_a_copy():
    assert engagement_offer_ids is canonical_offer_ids


def test_optional_upsell_recommendation_must_reference_a_real_catalog_offer():
    with pytest.raises(SchemaValidationError, match="consulting_offers catalog"):
        ConsultingEngagementRequest(**_BASE_KWARGS, optional_upsell_recommendations=("not-a-real-offer-id",))


def test_optional_upsell_recommendation_accepts_a_real_catalog_offer_id():
    request = ConsultingEngagementRequest(**_BASE_KWARGS, optional_upsell_recommendations=("unit-service-economics",))
    assert request.optional_upsell_recommendations == ("unit-service-economics",)


def test_every_canonical_offer_id_is_a_valid_upsell_recommendation():
    for offer_id in canonical_offer_ids:
        request = ConsultingEngagementRequest(**_BASE_KWARGS, optional_upsell_recommendations=(offer_id,))
        assert request.optional_upsell_recommendations == (offer_id,)
