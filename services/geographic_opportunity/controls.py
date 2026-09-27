"""services.geographic_opportunity.controls -- negative controls for the
geographic price-asymmetry / trade-feasibility service.

Credential-shaped-value and raw-HTML detection are copied verbatim from
``backend.adapters.research.supplier_feasibility`` (``SECRET_KEY``/
``SECRET_VALUE``/``HTML_MARKERS``), re-declared rather than imported to
match this repository's own established convention for this exact check
(see that module's sibling adapters, each of which carries its own copy
rather than sharing one).

This module also holds the controls specific to this domain: FX
provenance (a currency conversion must name its own rate source, never
just "assumed"), currency-mismatch enforcement (reusing
``backend.economics.kernel.CurrencyMismatchError``), missing-value
enforcement, the single ``is_verified`` gate for "may this observation be
treated as verified", and a structural check that no regulatory
observation ever claims an affirmative clearance this service has no
authority to grant.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from backend.economics.kernel import CurrencyMismatchError, EvidenceRef, Money

from .schemas import REGULATORY_STATUSES, FieldEvidence

# Copied verbatim from backend.adapters.research.supplier_feasibility.
_SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
_SECRET_VALUE = re.compile(r"(bearer\s+|sk_live_|sk_test_|ghp_|xox[baprs]-|-----BEGIN)", re.I)
_HTML_MARKERS = re.compile(r"<(?:!DOCTYPE\s+html|html|body|script)\b", re.I)

# Rate sources this module accepts as an explicit FX provenance. "assumed"
# and "unknown" are deliberately absent: a currency conversion that only
# claims those is exactly the "currency conversion without explicit
# provenance" the mission requires this service reject.
_ACCEPTABLE_FX_SOURCES = frozenset({
    "manual_import", "fixture", "central_bank_reference_rate", "commercial_bank_rate", "market_spot_rate",
})


class NegativeControlError(ValueError):
    """Raised when caller-supplied input fails a negative control check."""


class FxProvenanceError(NegativeControlError):
    """Raised when a currency-converted ``Money`` value does not name an
    explicit, acceptable FX rate source."""


class UnsupportedRegulatoryInferenceError(NegativeControlError):
    """Raised when a caller attempts to assert a regulatory status this
    service has no authority to grant (e.g. an affirmative clearance)."""


def contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_SECRET_KEY.search(str(key)) or contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item) for item in value)
    return bool(_SECRET_VALUE.search(str(value))) if value is not None else False


def contains_html(value: Any) -> bool:
    """Detect raw HTML document/script markers. A lone '<' is not HTML."""
    if isinstance(value, Mapping):
        return any(contains_html(key) or contains_html(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_html(item) for item in value)
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview)):
        text = bytes(value).decode("utf-8", errors="replace")
    else:
        text = str(value)
    return bool(_HTML_MARKERS.search(text))


def reject_unsafe_input(value: Any, *, field_name: str = "input") -> None:
    """Raise ``NegativeControlError`` if ``value`` contains
    credential-shaped content or raw HTML."""
    if contains_secret(value):
        raise NegativeControlError(f"{field_name} contains credential-shaped content")
    if contains_html(value):
        raise NegativeControlError(f"{field_name} contains raw HTML")


def require_matching_currency(*monies: Money | None, field_name: str = "monetary fields") -> None:
    """Assert every non-``None`` ``Money`` in ``monies`` shares one
    currency. ``Money``'s own arithmetic already raises
    ``CurrencyMismatchError`` on a mismatched add/sub; this is a
    pre-flight equality check for the places (pairing a destination price
    with an origin cost, a trade-flow value with a lane) where no
    arithmetic happens yet."""
    currencies = {money.currency for money in monies if money is not None}
    if len(currencies) > 1:
        raise CurrencyMismatchError()


def require_present(value: Any, *, field_name: str) -> Any:
    """Raise ``NegativeControlError`` if ``value`` is ``None``. Guards
    the "missing duty"/"missing supplier cost" negative controls: a
    landed-cost scenario must never silently treat a missing ``Money`` or
    rate as an assumed zero."""
    if value is None:
        raise NegativeControlError(f"{field_name} is required and must not be missing")
    return value


def require_fx_provenance(money: Money, *, field_name: str = "money") -> Money:
    """Assert that if ``money`` carries an FX conversion (``exchange_rate``
    is set -- ``backend.economics.kernel.Money`` already structurally
    requires ``exchange_rate_timestamp`` whenever that is set), its
    ``source`` names an acceptable, explicit rate source rather than
    ``"assumed"``/``"unknown"``/empty. A ``Money`` with no
    ``exchange_rate`` at all (no conversion happened) always passes --
    this control only fires on values this module or a caller is
    treating as *converted*."""
    if money.exchange_rate is not None and money.source not in _ACCEPTABLE_FX_SOURCES:
        raise FxProvenanceError(
            f"{field_name} carries a currency conversion (exchange_rate={money.exchange_rate}) "
            f"without an explicit, acceptable rate source (got source={money.source!r})"
        )
    return money


def reject_unsupported_regulatory_claim(status: str, *, field_name: str = "regulatory status") -> None:
    """Raise ``UnsupportedRegulatoryInferenceError`` if ``status`` is not
    one of ``schemas.REGULATORY_STATUSES`` -- defense in depth alongside
    ``RegulatoryComplianceObservation.__post_init__``'s own structural
    check, for any caller that builds a payload dict before constructing
    the dataclass (e.g. a client-safe export)."""
    if status not in REGULATORY_STATUSES:
        raise UnsupportedRegulatoryInferenceError(f"{field_name}={status!r} is not a supported, non-affirmative regulatory status")


_VERIFIED_EVIDENCE_STATES = frozenset({"verified", "observed", "live_readonly"})


def is_verified(evidence: FieldEvidence) -> bool:
    """The single gate for "may this observation be treated as verified".

    A supplier's or reporter's own claim -- ``quality="manual"``, or an
    ``evidence_ref`` that is not ``human_confirmed``, or whose
    ``evidence_state`` is not itself one of ``_VERIFIED_EVIDENCE_STATES``
    -- is never verified. Only a ``quality="observed"`` field backed by a
    ``human_confirmed`` ``EvidenceRef`` in a verified-like
    ``evidence_state`` counts.
    """
    if evidence.quality != "observed":
        return False
    ref = evidence.evidence_ref
    if ref is None or not isinstance(ref, EvidenceRef):
        return False
    if not ref.human_confirmed:
        return False
    return ref.evidence_state in _VERIFIED_EVIDENCE_STATES
