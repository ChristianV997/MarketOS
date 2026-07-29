"""backend.validation — product validation pipeline (Pipeline 2 of the
dropship spine: Discover → Validate → Create → Launch → Optimize).

Public surface:
    validate_product(product, retail_price=None)  → full validation verdict
    calculate_margin(...)                          → unit economics breakdown
    find_best_supplier(product)                    → cheapest reliable quote
"""
from backend.validation.margin_calculator import calculate_margin, suggest_retail_price
from backend.validation.suppliers import find_best_supplier, SupplierQuote
from backend.validation.validator import validate_product

__all__ = [
    "calculate_margin",
    "suggest_retail_price",
    "find_best_supplier",
    "SupplierQuote",
    "validate_product",
]
