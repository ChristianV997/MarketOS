"""evaluation.commerce.meta_ad_library_evidence -- offline advertiser-transparency
evidence from a supplied Meta Ad Library response shape (fixture and dry-run only).

Status (see docs/META_AD_LIBRARY_EVIDENCE.md for the full record):
- Implemented: this offline contract and normalizer.
- Tested: synthetic fixtures only.
- Dry-run: the bridge in backend.adapters.research.meta_ad_library.
- Not integration-tested. Not live-validated. No provider has been called.

Access requirements, terms, geography coverage, field availability and rate
limits for the Meta Ad Library API were NOT verified against Meta's primary
documentation in the session that wrote this module. This module maps only a
response shape the caller supplies. It has no transport, reads no environment
variables, loads no credentials, and opens no sockets.

Ad evidence describes public advertiser activity for research context. It is
not supplier proof, not product demand, and grants no publishing, spend, or
launch authority.

Field policy:
- Spend, impressions, delivery-by-region, demographic, reach and targeting or
  audience fields are never mapped or copied. They are reported as
  ``unavailable``, even when a response carries them. Only the field names are
  listed back.
- A field that is absent, malformed or out of scope is ``unavailable`` or
  ``malformed``. Nothing is inferred, estimated or defaulted.
- Snapshot references keep scheme, host and path only. Query strings, fragments
  and user information are removed or rejected, because they can carry tokens.

Sanitization policy (fail-closed, not complete): see the documentation for the
exact rules and the residual limits. Creative and advertiser text is withheld
entirely, never partly redacted, when it matches any of those rules.
"""
from __future__ import annotations

import html
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

SOURCE = "meta_ad_library_api"
SOURCE_STATUS = "candidate_primary_source_unverified"
EVIDENCE_TIER = "ad_transparency_offline_non_live"
ACCESS_METHOD = "offline_fixture"

# No transport exists, so no retry exists. A future transport PR must justify a non-zero value.
MAX_RETRY_ATTEMPTS = 0
MAX_INPUT_RECORDS = 500
MAX_SEARCH_TERMS_CHARS = 100
MAX_EXCERPT_CHARS = 280
MAX_PAGE_NAME_CHARS = 100
MAX_RAW_TEXT_CHARS = 2000
MAX_SNAPSHOT_CHARS = 2048

RESPONSE_STATUSES = (
    "ok",
    "partial",
    "rate_limited",
    "unavailable_access",
    "upstream_unavailable",
    "malformed_response",
    "no_offline_response",
    "invalid_request",
    "blocked_live_mode",
)

# Drops caused by the caller's filters. They are expected and do not make a response partial.
FILTER_REASONS = frozenset({"country_not_in_reached_countries", "outside_date_window"})

# Metrics and audience fields that this layer never maps. The scope that would permit them is unverified.
UNAVAILABLE_BY_POLICY = (
    "spend",
    "impressions",
    "delivery_by_region",
    "demographic_distribution",
    "estimated_audience_size",
    "eu_total_reach",
    "target_ages",
    "target_gender",
    "target_locations",
)


class _ReadOnlyMapping(Mapping):
    """A read-only mapping. It is not a dict, so no dict mutator applies. It pickles and deep-copies.

    Assignment raises TypeError because the class defines no ``__setitem__``. Storage is a mapping proxy, so the
    underlying dict cannot be changed through the object either.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_data", MappingProxyType(dict(data)))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("read-only mapping")

    def __reduce__(self) -> tuple[Any, ...]:
        return (_ReadOnlyMapping, (dict(self._data),))

    def __repr__(self) -> str:
        return f"_ReadOnlyMapping({dict(self._data)!r})"


# Authority is explicitly off. Consumers must not treat ad evidence as a decision input without a separate gate.
_AUTHORITY_VALUES = MappingProxyType(
    {
        "publish": False,
        "spend": False,
        "launch": False,
        "supplier_proof": False,
        "product_demand": False,
        "decision_scoring": False,
    }
)
AUTHORITY = _ReadOnlyMapping(_AUTHORITY_VALUES)

_ISO_COUNTRY = re.compile(r"^[A-Z]{2}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMERIC_ID = re.compile(r"^\d{1,30}$")
_AD_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_PLATFORM = re.compile(r"^[a-z_]{1,32}$")
_HTML_TAG = re.compile(r"<[^>]{0,200}>")

# Ten or more digits, separated by at most four non-word characters. Dash-grouped and slash-grouped numbers count.
_PHONE = re.compile(r"(?<!\d)\+?\d(?:[^\w\n]{0,4}\d){9,}(?!\d)")
# A label of letters or digits (any script), a full stop, and a top-level label of two or more letters.
_DOMAIN = re.compile(r"(?i)[^\W_][\w-]{0,62}\.[^\W\d_]{2,}")
_WWW = re.compile(r"(?i)(?<![a-z0-9])www(?![a-z0-9])")
_SCHEME = re.compile(r"(?i)(?<![a-z0-9])(?:(?:https?|ftp|javascript)\s*:|data:[\w.+-]+/)")
_BRACKETED_AT_DOT = re.compile(r"(?i)[\[({<]\s*(?:at|dot)\s*[\])}>]")
_TOKEN_PREFIX = re.compile(
    r"(?i)(?<![a-z0-9])(?:sk|pk|rk)[-_][a-z0-9_-]{8,}"
    r"|(?<![a-z0-9])(?:ghp|gho|ghu|ghs|ghr|github_pat)_[a-z0-9_]{8,}"
    r"|(?<![a-z0-9])xox[baprs]-[a-z0-9-]{8,}"
    r"|(?<![A-Za-z0-9])(?-i:AKIA[0-9A-Z]{16})"
    r"|(?<![A-Za-z0-9])(?-i:EAA[A-Za-z0-9]{12,})"
)
_KEYWORD = re.compile(
    r"(?i)(?:access[\s_-]*token|auth[\s_-]*token|api[\s_-]*key|private[\s_-]*key|bearer|password|passwd)"
    r"|(?<![a-z])secrets?(?![a-z])"
    r"|secret(?:key|token|value|code)"
)
_ALNUM_RUN = re.compile(r"[A-Za-z0-9]{16,}")
_SEPARATED_RUN = re.compile(r"[A-Za-z0-9_.-]{20,}")


def _has_letter_and_digit_run(text: str, pattern: re.Pattern[str]) -> bool:
    """Single-pass scan of maximal runs. Linear in the input, unlike lookaheads that rescan each start position."""
    for match in pattern.finditer(text):
        run = match.group()
        if any(ch.isdigit() for ch in run) and any(ch.isalpha() for ch in run):
            return True
    return False


@dataclass(frozen=True)
class AdLibraryRecord:
    ad_id: str
    page_id: str | None
    page_name: str | None
    delivery_start: str | None
    delivery_stop: str | None
    delivery_status: str
    countries: tuple[str, ...]
    platforms: tuple[str, ...]
    creative_excerpt: str | None
    creative_excerpt_truncated: bool
    snapshot_reference: str | None
    field_status: Mapping[str, str]
    policy_fields_present: tuple[str, ...]
    record_status: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ad_id": self.ad_id,
            "page_id": self.page_id,
            "page_name": self.page_name,
            "delivery_start": self.delivery_start,
            "delivery_stop": self.delivery_stop,
            "delivery_status": self.delivery_status,
            "countries": list(self.countries),
            "platforms": list(self.platforms),
            "creative_excerpt": self.creative_excerpt,
            "creative_excerpt_truncated": self.creative_excerpt_truncated,
            "snapshot_reference": self.snapshot_reference,
            "field_status": dict(self.field_status),
            "policy_fields_present": list(self.policy_fields_present),
            "record_status": self.record_status,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AdLibraryEvidenceReport:
    source: str
    source_status: str
    evidence_tier: str
    access_method: str
    response_status: str
    observed_at: float
    query: Mapping[str, Any]
    coverage: Mapping[str, Any]
    counts: Mapping[str, Any]
    records: tuple[AdLibraryRecord, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unavailable_by_policy: tuple[str, ...] = UNAVAILABLE_BY_POLICY
    authority: Mapping[str, bool] = field(default_factory=lambda: _ReadOnlyMapping(_AUTHORITY_VALUES))
    retry_attempts_allowed: int = MAX_RETRY_ATTEMPTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_status": self.source_status,
            "evidence_tier": self.evidence_tier,
            "access_method": self.access_method,
            "response_status": self.response_status,
            "observed_at": self.observed_at,
            "query": dict(self.query),
            "coverage": dict(self.coverage),
            "counts": {key: dict(value) if isinstance(value, Mapping) else value for key, value in self.counts.items()},
            "records": [record.to_dict() for record in self.records],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "unavailable_by_policy": list(self.unavailable_by_policy),
            "authority": dict(self.authority),
            "retry_attempts_allowed": self.retry_attempts_allowed,
        }


def make_report(
    response_status: str,
    *,
    search_terms: str,
    country: str,
    observed_at: float,
    date_min: str | None = None,
    date_max: str | None = None,
    records: tuple[AdLibraryRecord, ...] = (),
    received: int = 0,
    dropped: Mapping[str, int] | None = None,
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    first_page_only: bool = False,
) -> AdLibraryEvidenceReport:
    """Build a report. Callers pass only validated query values, and every mapping is read-only."""
    return AdLibraryEvidenceReport(
        source=SOURCE,
        source_status=SOURCE_STATUS,
        evidence_tier=EVIDENCE_TIER,
        access_method=ACCESS_METHOD,
        response_status=response_status,
        observed_at=observed_at,
        query=_ReadOnlyMapping(
            {"search_terms": search_terms, "country": country, "date_min": date_min, "date_max": date_max}
        ),
        coverage=_ReadOnlyMapping(
            {
                "first_page_only": first_page_only,
                "pagination_followed": False,
                "geography_rule": "country_must_appear_in_ad_reached_countries",
                "date_rule": "utc_calendar_day_of_delivery_start_inclusive",
                "coverage_statement": "not_verified_against_primary_documentation",
            }
        ),
        counts=_ReadOnlyMapping(
            {
                "received": received,
                "kept": len(records),
                "dropped": _ReadOnlyMapping(dict(dropped or {})),
            }
        ),
        records=records,
        blockers=blockers,
        warnings=warnings,
    )


_DOT_LIKE = str.maketrans({"\u3002": "."})
# Marks (combining, enclosing), format and control characters are removed from the detection form with no gap.
_CHECK_DROPPED = frozenset({"Mn", "Me", "Cf", "Cc"})
# Default-ignorable letters that are not category Cf. Hangul fillers render as nothing and can split a word.
_IGNORABLE_LETTERS = frozenset("\u115f\u1160\u3164\uffa0\u2065")


def _prepare(text: str) -> str:
    """Output form: entities decoded, NFKC, dot-like marks mapped, invisible characters removed. Accents are kept.

    Invisible characters (category ``Cf``) and control characters are deleted with no gap. Tab, newline, carriage
    return and vertical tab become spaces. Tags are still present. Detection does not run on this form.
    """
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(_DOT_LIKE)
    chars: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Cf":
            continue
        if category == "Cc":
            chars.append(" " if ch in "\t\n\r\x0b\x0c" else "")
            continue
        chars.append(ch)
    return "".join(chars)


def _check_form(text: str) -> str:
    """Detection form: entities decoded, NFKD, dot-like marks mapped, marks and invisible characters removed.

    Accented letters decompose into a base letter and a combining mark, so ``p\u00e1ssword`` is checked as
    ``password``. Combining marks, enclosing marks and variation selectors go with no gap, so ``<\ufe0fat>`` still
    reads as the bracketed word. Every detection rule runs on this form, with tags present and with tags removed.
    """
    text = unicodedata.normalize("NFKD", html.unescape(text)).translate(_DOT_LIKE)
    chars: list[str] = []
    for ch in text:
        if ch in "\t\n\r\x0b\x0c":
            chars.append(" ")
        elif ch not in _IGNORABLE_LETTERS and unicodedata.category(ch) not in _CHECK_DROPPED:
            chars.append(ch)
    return "".join(chars)


def _has_bracketed_at_dot(text: str) -> bool:
    """Bracket check on the detection form, before tags are removed, so ``<at>`` is seen."""
    return bool(_BRACKETED_AT_DOT.search(_check_form(text)))


def _clean(text: str) -> str:
    """Output text with tags removed and whitespace collapsed."""
    return " ".join(_HTML_TAG.sub("", _prepare(text)).split())


def _check_clean(text: str) -> str:
    """Detection form with tags removed and whitespace collapsed. Rule checks run on this text."""
    return " ".join(_HTML_TAG.sub("", _check_form(text)).split())


_MAX_DECODE_PASSES = 16


def _decode_fully(text: str) -> str | None:
    """Percent-decode until stable. Return None when the text still changes after the pass bound: withhold, do not guess."""
    for _ in range(_MAX_DECODE_PASSES):
        decoded = unquote(text)
        if decoded == text:
            return text
        text = decoded
    return None


def _normalize_bounded(value: str, limit: int) -> str | None:
    """NFKC-normalize, refusing when either the raw or the normalized length exceeds the limit.

    NFKC can expand a character many times over, so the bound is applied to the normalized text as well.
    """
    if len(value) > limit:
        return None
    normalized = unicodedata.normalize("NFKC", value)
    if len(normalized) > limit:
        return None
    return normalized


def _looks_sensitive(text: str, *, locator: bool = False) -> bool:
    """True when normalized text matches a contact, link or credential rule.

    ``locator`` marks a host or path. Host-level rules (domains, www, phone numbers) are skipped there, because a
    snapshot host is expected to be a domain. Credential, scheme and address rules still apply.
    """
    if "@" in text or _SCHEME.search(text) or _BRACKETED_AT_DOT.search(text):
        return True
    if not locator:
        if _WWW.search(text) or _DOMAIN.search(text):
            return True
        if _PHONE.search(text):
            return True
    return bool(
        _TOKEN_PREFIX.search(text)
        or _KEYWORD.search(text)
        or _has_letter_and_digit_run(text, _ALNUM_RUN)
        or _has_letter_and_digit_run(text, _SEPARATED_RUN)
    )


def _has_control_or_format(text: str) -> bool:
    return any(unicodedata.category(ch) in ("Cc", "Cf") for ch in text)


def _sanitize_text(value: Any, *, limit: int) -> tuple[str | None, bool, str | None]:
    """Return (text, truncated, withheld_reason). Sensitive-looking text is withheld, never partly redacted."""
    if not isinstance(value, str):
        return None, False, "not_text"
    normalized = _normalize_bounded(value, MAX_RAW_TEXT_CHARS)
    if normalized is None:
        return None, False, "withheld_oversized"
    if _has_bracketed_at_dot(normalized):
        return None, False, "withheld_sensitive"
    cleaned = _clean(normalized)
    if not cleaned:
        return None, False, "empty"
    if _looks_sensitive(_check_clean(normalized)):
        return None, False, "withheld_sensitive"
    if len(cleaned) > limit:
        return cleaned[:limit].rstrip(), True, None
    return cleaned, False, None


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except OverflowError:
        return None


def _snapshot_reference(value: Any) -> tuple[str | None, str | None]:
    """Return (reference, warning). The reference keeps scheme, host and path only. Absent input is silent."""
    if value is None:
        return None, None
    if not isinstance(value, str) or len(value) > MAX_SNAPSHOT_CHARS:
        return None, "snapshot_reference_malformed"
    stripped = value.strip()
    if _has_control_or_format(stripped) or any(ch.isspace() for ch in stripped):
        return None, "snapshot_reference_malformed"
    try:
        parts = urlsplit(stripped)
    except ValueError:
        return None, "snapshot_reference_malformed"
    if parts.scheme != "https" or not parts.netloc or "@" in parts.netloc:
        return None, "snapshot_reference_malformed"

    decoded_host = _decode_fully(parts.netloc)
    decoded_path = _decode_fully(parts.path)
    if decoded_host is None or decoded_path is None:
        return None, "snapshot_reference_withheld"
    host_text = _normalize_bounded(decoded_host, MAX_SNAPSHOT_CHARS)
    path_text = _normalize_bounded(decoded_path, MAX_SNAPSHOT_CHARS)
    if host_text is None or path_text is None:
        return None, "snapshot_reference_withheld"
    # Both forms are checked: tags are present in the returned reference, so a tag cannot hide what it contains.
    for part in (host_text, path_text):
        if _looks_sensitive(_check_form(part), locator=True) or _looks_sensitive(_check_clean(part), locator=True):
            return None, "snapshot_reference_withheld"
    return urlunsplit(("https", parts.netloc, parts.path, "", "")), None


def _countries(value: Any) -> tuple[tuple[str, ...], int] | None:
    if not isinstance(value, list):
        return None
    kept: list[str] = []
    invalid = 0
    for item in value:
        if isinstance(item, str) and _ISO_COUNTRY.fullmatch(item):
            kept.append(item)
        else:
            invalid += 1
    return tuple(dict.fromkeys(kept)), invalid


def _platforms(value: Any) -> tuple[tuple[str, ...], int]:
    if not isinstance(value, list):
        return (), 0
    kept: list[str] = []
    invalid = 0
    for item in value:
        if isinstance(item, str) and _PLATFORM.fullmatch(item):
            kept.append(item)
        else:
            invalid += 1
    return tuple(dict.fromkeys(kept)), invalid


def validate_request(search_terms: Any, country: Any, date_min: Any, date_max: Any, observed_at: Any) -> str | None:
    """Return the first request-level refusal code, or None. Never echoes the rejected value."""
    if not isinstance(search_terms, str):
        return "search_terms_not_text"
    stripped = search_terms.strip()
    if not stripped or len(stripped) > MAX_SEARCH_TERMS_CHARS or _has_control_or_format(stripped):
        return "search_terms_invalid"
    normalized_terms = _normalize_bounded(stripped, MAX_RAW_TEXT_CHARS)
    if normalized_terms is None or _has_bracketed_at_dot(normalized_terms):
        return "search_terms_withheld_sensitive"
    if _looks_sensitive(_check_clean(normalized_terms)):
        return "search_terms_withheld_sensitive"
    if not isinstance(country, str) or not _ISO_COUNTRY.fullmatch(country):
        return "country_invalid"
    for window in (date_min, date_max):
        if window is None:
            continue
        if not isinstance(window, str) or not _ISO_DATE.fullmatch(window):
            return "date_window_invalid"
        try:
            date.fromisoformat(window)
        except ValueError:
            return "date_window_invalid"
    if date_min is not None and date_max is not None and date_min > date_max:
        return "date_window_inverted"
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
        return "observed_at_invalid"
    try:
        value = float(observed_at)
    except OverflowError:
        return "observed_at_invalid"
    if not math.isfinite(value):
        return "observed_at_invalid"
    return None


def _map_record(
    item: Any,
    *,
    country: str,
    date_min: str | None,
    date_max: str | None,
) -> tuple[AdLibraryRecord | None, str | None]:
    """Map one archive entry. Return (record, None) when kept, or (None, drop_reason) when excluded."""
    if not isinstance(item, Mapping):
        return None, "malformed_entry"
    ad_id = item.get("id")
    if not isinstance(ad_id, str) or not _AD_ID.fullmatch(ad_id):
        return None, "missing_or_invalid_id"

    warnings: list[str] = []
    field_status: dict[str, str] = {}

    raw_page_id = item.get("page_id")
    if raw_page_id is None:
        page_id, field_status["page_id"] = None, "unavailable"
    elif isinstance(raw_page_id, str) and _NUMERIC_ID.fullmatch(raw_page_id):
        page_id, field_status["page_id"] = raw_page_id, "observed"
    else:
        page_id, field_status["page_id"] = None, "malformed"
        warnings.append("page_id_malformed")

    page_name, truncated_name, withheld = _sanitize_text(item.get("page_name"), limit=MAX_PAGE_NAME_CHARS)
    if page_name is not None and not truncated_name:
        field_status["page_name"] = "observed"
    else:
        # A truncated advertiser name would be a different name, so it is withheld rather than shortened.
        page_name = None
        field_status["page_name"] = "unavailable"
        if truncated_name:
            warnings.append("page_name_too_long")
        elif withheld not in (None, "not_text", "empty"):
            warnings.append("page_name_withheld")

    start = _instant(item.get("ad_delivery_start_time"))
    if start is not None:
        field_status["delivery_start"] = "observed"
    elif item.get("ad_delivery_start_time") is None:
        field_status["delivery_start"] = "unavailable"
    else:
        field_status["delivery_start"] = "malformed"
        warnings.append("delivery_start_malformed")

    stop = _instant(item.get("ad_delivery_stop_time"))
    if item.get("ad_delivery_stop_time") is None:
        field_status["delivery_stop"] = "unavailable"
    elif stop is None:
        field_status["delivery_stop"] = "malformed"
        warnings.append("delivery_stop_malformed")
    elif start is not None and stop < start:
        stop = None
        field_status["delivery_stop"] = "malformed"
        warnings.append("delivery_stop_before_start")
    else:
        field_status["delivery_stop"] = "observed"

    # A status needs a trustworthy start. A malformed stop leaves the state unknown, so it is not inferred either way.
    if start is None or field_status["delivery_stop"] == "malformed":
        delivery_status = "unavailable"
    elif stop is not None:
        delivery_status = "ended"
    else:
        delivery_status = "delivering"
    field_status["delivery_status"] = "derived" if delivery_status != "unavailable" else "unavailable"

    countries_result = _countries(item.get("ad_reached_countries"))
    if countries_result is None:
        countries: tuple[str, ...] = ()
        field_status["countries"] = "unavailable" if item.get("ad_reached_countries") is None else "malformed"
    else:
        countries, invalid_countries = countries_result
        field_status["countries"] = "observed" if countries else "unavailable"
        if invalid_countries:
            warnings.append("countries_partially_invalid")

    platforms, invalid_platforms = _platforms(item.get("publisher_platforms"))
    field_status["platforms"] = "observed" if platforms else "unavailable"
    if invalid_platforms:
        warnings.append("platforms_partially_invalid")

    # Geography and date-window filters run before any text is returned, so excluded records leak nothing.
    if not countries:
        return None, "geography_unavailable"
    if country not in countries:
        return None, "country_not_in_reached_countries"
    if date_min is not None or date_max is not None:
        if start is None:
            return None, "date_unverifiable"
        start_day = start.date().isoformat()
        if (date_min is not None and start_day < date_min) or (date_max is not None and start_day > date_max):
            return None, "outside_date_window"

    bodies = item.get("ad_creative_bodies")
    first_body = bodies[0] if isinstance(bodies, list) and bodies else None
    excerpt, truncated, withheld = _sanitize_text(first_body, limit=MAX_EXCERPT_CHARS)
    if excerpt is not None:
        field_status["creative_excerpt"] = "observed"
        if truncated:
            warnings.append("creative_excerpt_truncated")
    else:
        field_status["creative_excerpt"] = "unavailable"
        if withheld not in (None, "not_text", "empty"):
            warnings.append("creative_excerpt_withheld")

    snapshot, snapshot_warning = _snapshot_reference(item.get("ad_snapshot_url"))
    if snapshot is not None:
        field_status["snapshot_reference"] = "observed"
    else:
        field_status["snapshot_reference"] = "unavailable" if item.get("ad_snapshot_url") is None else "malformed"
        if snapshot_warning:
            warnings.append(snapshot_warning)

    for policy_field in UNAVAILABLE_BY_POLICY:
        field_status[policy_field] = "unavailable"
    policy_present = tuple(name for name in UNAVAILABLE_BY_POLICY if name in item)

    degraded = any(status == "malformed" for status in field_status.values()) or bool(warnings)
    record = AdLibraryRecord(
        ad_id=ad_id,
        page_id=page_id,
        page_name=page_name,
        delivery_start=start.isoformat() if start is not None else None,
        delivery_stop=stop.isoformat() if stop is not None else None,
        delivery_status=delivery_status,
        countries=countries,
        platforms=platforms,
        creative_excerpt=excerpt,
        creative_excerpt_truncated=truncated,
        snapshot_reference=snapshot,
        field_status=_ReadOnlyMapping(field_status),
        policy_fields_present=policy_present,
        record_status="partial" if degraded else "ok",
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return record, None


def _build_ad_library_evidence(
    response: Mapping[str, Any] | None,
    *,
    search_terms: str,
    country: str,
    observed_at: float,
    date_min: str | None = None,
    date_max: str | None = None,
) -> AdLibraryEvidenceReport:
    """Normalize one supplied response shape, ``{"http_status": int, "body": {...}}``, into evidence.

    Fails closed: every unexpected shape yields a named status with no records. Error bodies are read for their
    status only. Their messages are never echoed, because provider messages can embed request values.
    """
    request_error = validate_request(search_terms, country, date_min, date_max, observed_at)
    if request_error is not None:
        # Invalid input is not echoed back: no query value, country or window is reflected.
        return make_report("invalid_request", search_terms="", country="", observed_at=0.0, blockers=(request_error,))

    term = search_terms.strip()
    report_args = {
        "search_terms": term,
        "country": country,
        "observed_at": float(observed_at),
        "date_min": date_min,
        "date_max": date_max,
    }

    if response is None:
        return make_report("no_offline_response", **report_args, blockers=("no_offline_response_supplied",))
    if not isinstance(response, Mapping):
        return make_report("malformed_response", **report_args, blockers=("response_not_mapping",))

    http_status = response.get("http_status")
    if http_status == 429:
        return make_report(
            "rate_limited",
            **report_args,
            blockers=("provider_rate_limited", "retry_not_permitted_in_offline_layer"),
        )
    if http_status in (401, 403):
        return make_report(
            "unavailable_access",
            **report_args,
            blockers=("provider_access_refused", "developer_access_unverified"),
        )
    if isinstance(http_status, int) and http_status >= 500:
        return make_report("upstream_unavailable", **report_args, blockers=("provider_upstream_unavailable",))
    if not isinstance(http_status, int) or not 200 <= http_status < 300:
        return make_report("malformed_response", **report_args, blockers=("unexpected_http_status",))

    body = response.get("body")
    if not isinstance(body, Mapping):
        return make_report("malformed_response", **report_args, blockers=("body_not_mapping",))
    if "error" in body:
        return make_report("malformed_response", **report_args, blockers=("error_body_on_success_status",))
    data = body.get("data")
    if not isinstance(data, list):
        return make_report("malformed_response", **report_args, blockers=("data_not_list",))

    paging = body.get("paging")
    first_page_only = isinstance(paging, Mapping) and bool(paging.get("next"))
    warnings: list[str] = []
    dropped: dict[str, int] = {}
    if len(data) > MAX_INPUT_RECORDS:
        warnings.append("record_limit_exceeded")
        dropped["record_limit"] = len(data) - MAX_INPUT_RECORDS

    records: list[AdLibraryRecord] = []
    seen_ids: set[str] = set()
    for item in data[:MAX_INPUT_RECORDS]:
        record, reason = _map_record(item, country=country, date_min=date_min, date_max=date_max)
        if record is None:
            key = reason or "unknown"
            dropped[key] = dropped.get(key, 0) + 1
            continue
        # Deduplicate after the filters, so a filtered-out entry never shadows a valid one with the same identifier.
        if record.ad_id in seen_ids:
            dropped["duplicate_id"] = dropped.get("duplicate_id", 0) + 1
            continue
        seen_ids.add(record.ad_id)
        records.append(record)

    records.sort(key=lambda record: record.ad_id)
    data_quality_drops = any(key not in FILTER_REASONS for key in dropped)
    any_partial = any(record.record_status == "partial" for record in records)
    status = "partial" if (first_page_only or data_quality_drops or any_partial or warnings) else "ok"
    if first_page_only:
        warnings.append("first_page_only_pagination_not_followed")
    return make_report(
        status,
        **report_args,
        records=tuple(records),
        received=len(data),
        dropped=dropped,
        warnings=tuple(dict.fromkeys(warnings)),
        first_page_only=first_page_only,
    )


def build_ad_library_evidence(
    response: Mapping[str, Any] | None,
    *,
    search_terms: str,
    country: str,
    observed_at: float,
    date_min: str | None = None,
    date_max: str | None = None,
) -> AdLibraryEvidenceReport:
    """Fail-closed entry point. Any unexpected exception becomes a fixed malformed result, never a raise."""
    try:
        return _build_ad_library_evidence(
            response,
            search_terms=search_terms,
            country=country,
            observed_at=observed_at,
            date_min=date_min,
            date_max=date_max,
        )
    except Exception:
        return make_report("malformed_response", search_terms="", country="", observed_at=0.0, blockers=("offline_builder_failed",))
