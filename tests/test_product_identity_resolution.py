"""Focused tests for conservative cross-source product identity resolution.

Synthetic fixtures only — no credentials, providers, network, or live upgrades.
"""
from __future__ import annotations

import pytest

from evaluation.commerce.product_identity_resolution import (
    MATCH_STATES,
    ProductObservation,
    resolve_product_identity,
)


def _obs(**overrides: object) -> ProductObservation:
    base = {
        "observation_id": "obs-1",
        "workspace_id": "ws-a",
        "source_kind": "marketplace",
        "source_system": "amazon",
        "source_record_id": "listing-1",
        "title": "Acme Widget Pro 2-Pack",
        "brand": "Acme",
        "model": "WP-200",
        "gtin": "012345678905",
        "evidence_mode": "fixture",
        "observed_at": "2026-01-01T00:00:00Z",
        "currency": "USD",
    }
    base.update(overrides)
    return ProductObservation(**base)  # type: ignore[arg-type]


def test_exact_cross_source_gtin_match_links_marketplace_and_supplier():
    marketplace = _obs(
        observation_id="mkt-1",
        source_kind="marketplace",
        source_system="amazon",
        source_record_id="B00EXACT01",
        asin="B00EXACT01",
        gtin="012345678905",
        evidence_mode="fixture",
    )
    supplier = _obs(
        observation_id="sup-1",
        source_kind="supplier",
        source_system="cj",
        source_record_id="cj-offer-99",
        gtin="0012345678905",  # EAN-13 form of the same UPC-12
        asin="",
        seller_sku="SELLER-LOCAL-1",
        evidence_mode="manual_import",
    )

    report = resolve_product_identity([marketplace, supplier])
    by_id = {link.observation_id: link for link in report.links}

    assert by_id["mkt-1"].match_state == "exact_match"
    assert by_id["sup-1"].match_state == "exact_match"
    assert by_id["mkt-1"].candidate_key == by_id["sup-1"].candidate_key
    assert "gtin" in by_id["mkt-1"].match_basis
    # Evidence modes preserved; never upgraded to live
    assert by_id["mkt-1"].evidence_mode == "fixture"
    assert by_id["sup-1"].evidence_mode == "manual_import"
    assert report.evidence_modes_seen == ("fixture", "manual_import")


def test_duplicate_observations_collapse_idempotently():
    a = _obs(observation_id="dup-a", source_record_id="same-listing")
    b = _obs(observation_id="dup-b", source_record_id="same-listing")
    report = resolve_product_identity([a, b])
    keys = {link.candidate_key for link in report.links}
    assert len(keys) == 1
    assert all(link.match_state == "exact_match" for link in report.links)
    assert "source_record" in report.links[0].match_basis


def test_conflicting_gtins_same_title_yield_conflict():
    a = _obs(observation_id="c1", gtin="012345678905", title="Same Title Widget")
    b = _obs(
        observation_id="c2",
        source_record_id="listing-2",
        gtin="098765432109",
        title="Same Title Widget",
        brand="Acme",
        model="WP-200",
    )
    report = resolve_product_identity([a, b])
    states = {link.observation_id: link.match_state for link in report.links}
    # Distinct strong identifiers must not merge; conflict when attributes otherwise align
    assert states["c1"] == "conflict" or states["c2"] == "conflict"
    assert {link.candidate_key for link in report.links} == {
        report.links[0].candidate_key,
        report.links[1].candidate_key,
    }
    assert len({link.candidate_key for link in report.links}) == 2


def test_same_title_different_brand_model_does_not_auto_merge():
    a = _obs(
        observation_id="t1",
        gtin="",
        asin="",
        mpn="",
        title="Wireless Earbuds Case",
        brand="BrandA",
        model="X1",
    )
    b = _obs(
        observation_id="t2",
        source_record_id="listing-2",
        gtin="",
        asin="",
        mpn="",
        title="Wireless Earbuds Case",
        brand="BrandB",
        model="Y9",
    )
    report = resolve_product_identity([a, b])
    assert len({link.candidate_key for link in report.links}) == 2
    assert all(
        link.match_state in {"unmatched", "possible_match", "ambiguous", "conflict"}
        for link in report.links
    )
    assert all(link.match_state != "exact_match" for link in report.links)


def test_variant_pack_size_conflict_blocks_auto_merge():
    a = _obs(
        observation_id="v1",
        gtin="",
        asin="",
        brand="Acme",
        mpn="WP-200",
        pack_size="2",
        title="Acme Widget Pro",
    )
    b = _obs(
        observation_id="v2",
        source_kind="supplier",
        source_system="cj",
        source_record_id="cj-2",
        gtin="",
        asin="",
        brand="Acme",
        mpn="WP-200",
        pack_size="6",
        title="Acme Widget Pro",
        evidence_mode="manual_import",
    )
    report = resolve_product_identity([a, b])
    assert len({link.candidate_key for link in report.links}) == 2
    assert any(link.match_state == "conflict" for link in report.links)
    assert all(link.match_state != "exact_match" for link in report.links)


def test_name_only_match_is_possible_or_ambiguous_never_exact():
    a = _obs(
        observation_id="n1",
        gtin="",
        asin="",
        mpn="",
        brand="",
        model="",
        title="Portable Mini Thermal Printer",
    )
    b = _obs(
        observation_id="n2",
        source_kind="consumer_attention",
        source_system="tiktok",
        source_record_id="tt-1",
        gtin="",
        asin="",
        mpn="",
        brand="",
        model="",
        title="Portable Mini Thermal Printer",
        evidence_mode="fixture",
    )
    report = resolve_product_identity([a, b])
    states = {link.match_state for link in report.links}
    assert states <= {"possible_match", "ambiguous", "unmatched"}
    assert "exact_match" not in states
    # Consumer attention remains distinct evidence class in report
    kinds = {link.source_kind for link in report.links}
    assert "consumer_attention" in kinds
    assert "marketplace" in kinds


def test_weak_seller_sku_alone_never_cross_source_exact_match():
    marketplace = _obs(
        observation_id="sku-m",
        gtin="",
        asin="",
        mpn="",
        brand="Acme",
        model="",
        seller_sku="SKU-123",
        seller_id="seller-amazon-1",
        title="Generic Cable",
    )
    supplier = _obs(
        observation_id="sku-s",
        source_kind="supplier",
        source_system="cj",
        source_record_id="cj-sku",
        gtin="",
        asin="",
        mpn="",
        brand="Acme",
        model="",
        seller_sku="SKU-123",
        seller_id="seller-cj-9",
        title="Generic Cable",
        evidence_mode="manual_import",
    )
    report = resolve_product_identity([marketplace, supplier])
    assert all(link.match_state != "exact_match" for link in report.links)
    assert len({link.candidate_key for link in report.links}) == 2


def test_seller_sku_exact_within_same_seller_and_source_system():
    a = _obs(
        observation_id="ss-1",
        gtin="",
        asin="",
        mpn="",
        seller_sku="SKU-123",
        seller_id="seller-1",
        source_system="amazon",
        source_record_id="L1",
    )
    b = _obs(
        observation_id="ss-2",
        gtin="",
        asin="",
        mpn="",
        seller_sku="SKU-123",
        seller_id="seller-1",
        source_system="amazon",
        source_record_id="L2",
        title="Acme Widget Pro 2-Pack refreshed",
    )
    report = resolve_product_identity([a, b])
    assert {link.candidate_key for link in report.links}
    assert len({link.candidate_key for link in report.links}) == 1
    assert all(link.match_state == "exact_match" for link in report.links)
    assert "seller_sku_scoped" in report.links[0].match_basis


def test_workspace_isolation_prevents_cross_workspace_merge():
    a = _obs(observation_id="w1", workspace_id="ws-a", gtin="012345678905")
    b = _obs(
        observation_id="w2",
        workspace_id="ws-b",
        source_record_id="listing-other",
        gtin="012345678905",
    )
    report = resolve_product_identity([a, b])
    assert len({link.candidate_key for link in report.links}) == 2
    assert all(link.workspace_id in {"ws-a", "ws-b"} for link in report.links)
    # Each may be unmatched or exact within its singleton cluster, but not shared
    assert {link.workspace_id for link in report.links if link.candidate_key == report.links[0].candidate_key} == {
        report.links[0].workspace_id
    }


def test_deterministic_under_reordered_inputs():
    records = [
        _obs(observation_id="d1", gtin="012345678905", source_record_id="A"),
        _obs(
            observation_id="d2",
            source_kind="supplier",
            source_system="cj",
            source_record_id="B",
            gtin="012345678905",
            evidence_mode="manual_import",
        ),
        _obs(
            observation_id="d3",
            gtin="",
            asin="",
            mpn="",
            brand="",
            title="Unrelated Name Only Item",
            source_record_id="C",
        ),
    ]
    forward = resolve_product_identity(records).to_dict()
    reverse = resolve_product_identity(list(reversed(records))).to_dict()
    assert forward["links"] == reverse["links"]
    assert forward["candidates"] == reverse["candidates"]


def test_brand_mpn_exact_match_across_sources():
    a = _obs(
        observation_id="bm1",
        gtin="",
        asin="",
        brand="Acme",
        mpn="WP-200-BLK",
        pack_size="1",
        source_kind="marketplace",
    )
    b = _obs(
        observation_id="bm2",
        gtin="",
        asin="",
        brand="acme",
        mpn="wp-200-blk",
        pack_size="1",
        source_kind="supplier",
        source_system="cj",
        source_record_id="cj-bm",
        evidence_mode="manual_import",
    )
    report = resolve_product_identity([a, b])
    assert len({link.candidate_key for link in report.links}) == 1
    assert all(link.match_state == "exact_match" for link in report.links)
    assert "brand_mpn" in report.links[0].match_basis


def test_does_not_invent_gtin_or_treat_event_ids_as_product_identity():
    a = _obs(
        observation_id="evt-1",
        gtin="",
        asin="",
        mpn="",
        brand="",
        model="",
        title="Something",
        event_id="evt-shared-123",
        source_record_id="sr-1",
    )
    b = _obs(
        observation_id="evt-2",
        gtin="",
        asin="",
        mpn="",
        brand="",
        model="",
        title="Different Product Entirely",
        event_id="evt-shared-123",
        source_record_id="sr-2",
    )
    report = resolve_product_identity([a, b])
    assert len({link.candidate_key for link in report.links}) == 2
    assert all(link.match_state != "exact_match" for link in report.links)
    for link in report.links:
        assert not link.candidate_key.startswith("gtin:")
        assert "event_id" not in link.match_basis


def test_match_states_vocabulary_is_closed():
    assert MATCH_STATES == (
        "exact_match",
        "possible_match",
        "ambiguous",
        "conflict",
        "unmatched",
    )


def test_rejects_blank_workspace_or_observation_id():
    with pytest.raises(ValueError):
        _obs(workspace_id="")
    with pytest.raises(ValueError):
        _obs(observation_id="  ")


def test_consumer_attention_not_treated_as_supplier_or_price_proof():
    attention = _obs(
        observation_id="ca-1",
        source_kind="consumer_attention",
        source_system="reddit",
        source_record_id="r-1",
        gtin="012345678905",
        evidence_mode="fixture",
        title="Love my Acme Widget Pro",
    )
    supplier = _obs(
        observation_id="sup-ca",
        source_kind="supplier",
        source_system="cj",
        source_record_id="cj-ca",
        gtin="012345678905",
        evidence_mode="manual_import",
    )
    report = resolve_product_identity([attention, supplier])
    # May exact-link on GTIN for identity, but evidence classes stay labeled
    by_id = {link.observation_id: link for link in report.links}
    assert by_id["ca-1"].source_kind == "consumer_attention"
    assert by_id["sup-ca"].source_kind == "supplier"
    assert by_id["ca-1"].evidence_mode == "fixture"
    assert "live" not in by_id["ca-1"].evidence_mode
    assert report.pillar_separation["consumer_attention_is_not_supplier_proof"] is True
    assert report.pillar_separation["consumer_attention_is_not_marketplace_price_proof"] is True
