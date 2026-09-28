"""Canonical, offline Decimal contracts for MarketOS commercial economics.

This module is the single authority for new money arithmetic.  Existing
float-shaped reports may adapt its results at their public boundary, but must
not reimplement the formulas.  FX conversion is deliberately explicit: a
currency value cannot be converted with a hidden table or a universal rate.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


SUPPORTED_CURRENCIES = frozenset({"CAD", "EUR", "GBP", "MXN", "USD"})
EVIDENCE_STATES = frozenset({
    "unknown", "missing", "assumed", "derived", "fixture", "simulated",
    "observed", "live_readonly", "verified", "stale", "rejected",
})
TAX_INCLUSION_STATES = frozenset({"unknown", "inclusive", "exclusive", "not_applicable"})
_ZERO = Decimal("0")
_ONE = Decimal("1")
_THIRTY = Decimal("30")
