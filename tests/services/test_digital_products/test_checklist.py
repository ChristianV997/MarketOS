"""Tests for services.digital_products.checklist.build_launch_checklist."""
from services.digital_products.checklist import build_launch_checklist
from services.digital_products.funnel import build_funnel_plan
from services.digital_products.offer import create_digital_offer
from services.digital_products.validation import validate_digital_product


def test_checklist_reflects_validation_verdict():
    offer = create_digital_offer("Thing", target_customer="marketers", price=99.0)
    funnel = build_funnel_plan(offer)
    weak_validation = validate_digital_product(offer, target_buyers=500)
    strong_validation = validate_digital_product(offer, target_buyers=5, has_existing_audience=True)

    weak_checklist = build_launch_checklist(offer, funnel, weak_validation)
    strong_checklist = build_launch_checklist(offer, funnel, strong_validation)

    def _find(checklist, substr):
        return next(item for item in checklist if substr in item["item"])

    assert _find(weak_checklist, "viable or strong")["done"] is False
    assert _find(strong_checklist, "viable or strong")["done"] is True


def test_checklist_flags_missing_target_customer():
    offer = create_digital_offer("Thing", target_customer="", price=99.0)
    funnel = build_funnel_plan(offer)
    validation = validate_digital_product(offer, target_buyers=5, has_existing_audience=True)
    checklist = build_launch_checklist(offer, funnel, validation)
    defined_item = next(item for item in checklist if "target customer" in item["item"])
    assert defined_item["done"] is False
