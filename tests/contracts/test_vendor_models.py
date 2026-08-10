from backend.providers.vendor_catalog import list_vendor_capability_records
from backend.providers.vendor_models import VendorCapability


def test_vendor_capability_round_trip_is_json_safe() -> None:
    record = next(item for item in list_vendor_capability_records() if item.vendor_id == "google_news_rss")
    restored = VendorCapability.from_dict(record.to_dict())
    assert restored == record
    assert restored.source_urls[0].startswith("https://")


def test_write_capable_record_requires_approval() -> None:
    # The current catalog keeps live mutation false. Model semantics prohibit an unsafe record.
    record = next(item for item in list_vendor_capability_records() if item.vendor_id == "zendrop_mcp")
    assert record.approval_required
