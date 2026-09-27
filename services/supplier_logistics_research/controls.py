"""services.supplier_logistics_research.controls -- negative controls.

Credential-shaped-value and raw-HTML detection are copied verbatim from
``backend.adapters.research.supplier_feasibility`` (``SECRET_KEY``/
``SECRET_VALUE``/``HTML_MARKERS``); the cross-client marker convention
mirrors ``evaluation.companyos.service_delivery``'s own ``_LEAK_MARKERS``.
Both are re-declared here (not imported) to match this repository's
established per-module duplication style for this specific check, rather
than introducing a new shared dependency for it.

This module also holds the single gate for "may this field be treated as
verified evidence": ``is_verified``. Nothing downstream of this module may
promote a supplier's own claim to verified status by any other path.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from backend.economics.kernel import CurrencyMismatchError, EvidenceRef, Money

from .schemas import FieldEvidence

# Copied verbatim from backend.adapters.research.supplier_feasibility.
_SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
_SECRET_VALUE = re.compile(r"(bearer\s+|sk_live_|sk_test_|ghp_|xox[baprs]-|-----BEGIN)", re.I)
_HTML_MARKERS = re.compile(r"<(?:!DOCTYPE\s+html|html|body|script)\b", re.I)

# Mirrors evaluation.companyos.service_delivery._LEAK_MARKERS's convention,
# extended with this service's own candidate/client leakage vocabulary.
_CROSS_CLIENT_MARKERS = (
    "other_client",
    "cross_client",
    "another_client",
    "different_client",
    "different_candidate",
    "competing_candidate",
)


class NegativeControlError(ValueError):
    """Raised when caller-supplied input fails a negative control check."""


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


def contains_cross_client_reference(value: Any) -> bool:
    """Detect a stray reference to another client's/candidate's data
    inside a field meant to describe exactly one candidate's offer."""
    if isinstance(value, Mapping):
        return any(contains_cross_client_reference(key) or contains_cross_client_reference(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_cross_client_reference(item) for item in value)
    if value is None:
        return False
    lowered = str(value).lower()
    return any(marker in lowered for marker in _CROSS_CLIENT_MARKERS)


def reject_unsafe_input(value: Any, *, field_name: str = "input") -> None:
    """Raise ``NegativeControlError`` if ``value`` contains
    credential-shaped content, raw HTML, or a cross-client reference.
    Call this on every externally supplied string/mapping before it is
    used to build a ``schemas.py`` dataclass."""
    if contains_secret(value):
        raise NegativeControlError(f"{field_name} contains credential-shaped content")
    if contains_html(value):
        raise NegativeControlError(f"{field_name} contains raw HTML")
    if contains_cross_client_reference(value):
        raise NegativeControlError(f"{field_name} references another client/candidate")


def require_matching_currency(*monies: Money | None, field_name: str = "monetary fields") -> None:
    """Assert every non-``None`` ``Money`` in ``monies`` shares one
    currency. ``Money``'s own arithmetic already raises
    ``CurrencyMismatchError`` on a mismatched add/sub; this is a
    pre-flight equality check for the places (building a report, pairing
    a quoted price with a lane) where no arithmetic happens yet."""
    currencies = {money.currency for money in monies if money is not None}
    if len(currencies) > 1:
        raise CurrencyMismatchError()


def require_present(value: Any, *, field_name: str) -> Any:
    """Raise ``NegativeControlError`` if ``value`` is ``None``. Guards
    the "missing money" negative control: a landed-cost scenario must
    never silently treat a missing ``Money`` as an assumed zero."""
    if value is None:
        raise NegativeControlError(f"{field_name} is required and must not be missing")
    return value


_VERIFIED_EVIDENCE_STATES = frozenset({"verified", "observed", "live_readonly"})


def is_verified(evidence: FieldEvidence) -> bool:
    """The single gate for "may this field be treated as verified".

    A supplier's own claim -- ``quality="manual"``, or an
    ``evidence_ref`` that is not ``human_confirmed``, or whose
    ``evidence_state`` is not itself one of ``_VERIFIED_EVIDENCE_STATES``
    -- is never verified. Only a ``quality="observed"`` field backed by a
    ``human_confirmed`` ``EvidenceRef`` in a verified-like
    ``evidence_state`` counts. This is the only function in this service
    that may answer "is this verified" -- nothing downstream should
    re-derive that answer from ``quality`` or ``evidence_ref`` alone.
    """
    if evidence.quality != "observed":
        return False
    ref = evidence.evidence_ref
    if ref is None or not isinstance(ref, EvidenceRef):
        return False
    if not ref.human_confirmed:
        return False
    return ref.evidence_state in _VERIFIED_EVIDENCE_STATES
