from pathlib import Path
import tempfile

from backend.adapters.research.competition_evidence import import_csv

def test_import_csv_preserves_explicit_zero_vs_missing():
    # Setup temporary CSV file
    csv_content = """title,url,price,shipping_cost,currency
Product 1,http://example.com/1,10.50,5.00,USD
Product 2,http://example.com/2,,0.00,USD
Product 3,http://example.com/3,0.00,,USD
Product 4,http://example.com/4,,,USD
"""
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as tf:
        tf.write(csv_content)
        temp_path = tf.name

    try:
        offers = import_csv(temp_path)

        assert len(offers) == 4

        # Product 1: both present
        assert offers[0].title == "Product 1"
        assert offers[0].price == 10.50
        assert offers[0].shipping_cost == 5.00
        assert offers[0].field_status["price"] == "observed"
        assert offers[0].field_status["shipping_cost"] == "observed"

        # Product 2: price missing, shipping explicitly zero
        assert offers[1].title == "Product 2"
        assert offers[1].price is None
        assert offers[1].shipping_cost == 0.0
        assert offers[1].field_status["price"] == "missing"
        assert offers[1].field_status["shipping_cost"] == "observed"

        # Product 3: price explicitly zero, shipping missing
        assert offers[2].title == "Product 3"
        assert offers[2].price == 0.0
        assert offers[2].shipping_cost is None
        assert offers[2].field_status["price"] == "observed"
        assert offers[2].field_status["shipping_cost"] == "missing"

        # Product 4: both missing
        assert offers[3].title == "Product 4"
        assert offers[3].price is None
        assert offers[3].shipping_cost is None
        assert offers[3].field_status["price"] == "missing"
        assert offers[3].field_status["shipping_cost"] == "missing"

        # Ensure extraction_method marks this as offline manual import
        for offer in offers:
            assert offer.extraction_method == "manual_import"
            assert offer.source == "manual_csv_import"
    finally:
        Path(temp_path).unlink()
