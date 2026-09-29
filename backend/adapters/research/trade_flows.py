"""backend.adapters.research.trade_flows -- offline, pinned UN Comtrade
bulk-file adapter.

This adapter has no HTTP client and makes no live API calls. It reads a
manually-downloaded UN Comtrade bulk-download file (JSON or CSV) already
saved to local disk and normalizes it into plain, sanitized trade-flow
observation dicts. "Pinned" means: it recognizes exactly the field names
UN Comtrade's own bulk-download files are documented to use as of this
writing (``reporterISO``/``partnerISO``/``reporterCode``/``partnerCode``,
``cmdCode``, ``period``, ``primaryValue``, ``netWgt``, ``qtyUnitAbbr``,
``qty``) plus a small set of common export-tool variants, and does not
call ``comtradeapi.un.org`` or any other live endpoint, does not
authenticate, and does not page through a live result set.

Modeled directly on ``backend.adapters.research.supplier_feasibility``'s
own offline-importer pattern (no HTTP client, ``validate_input_path``,
secret/HTML rejection before any parsing, a normalize-then-collapse
pipeline) -- re-declared here rather than imported, matching this
repository's own established per-adapter duplication convention for this
exact check (that module's own docstring documents the same choice for
its siblings).

This module returns plain dicts, not ``services.geographic_opportunity``
dataclasses: ``backend/**`` never imports from ``services/**`` in this
repository (confirmed by a repo-wide grep before writing this file), so
the caller-side mapping into
``services.geographic_opportunity.schemas.BilateralTradeFlowObservation``
lives in the service layer, not here.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping

PINNED_SOURCE = "un_comtrade_bulk_download_v1"

# A local UN Comtrade bulk-download extract is legitimately larger than a
# single manual candidate file (thousands of rows), so this is looser
# than scripts/research_to_decision.py's 256 KiB single-document cap --
# but it is still a bound, not an unbounded read of an arbitrary local
# file, matching this repository's general "bounded local file" pattern.
MAX_BULK_FILE_BYTES = 5 * 1024 * 1024

# Copied verbatim from backend.adapters.research.supplier_feasibility.
SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
SECRET_VALUE = re.compile(r"(bearer\s+|sk_live_|sk_test_|ghp_|xox[baprs]-|-----BEGIN)", re.I)
HTML_MARKERS = re.compile(r"<(?:!DOCTYPE\s+html|html|body|script)\b", re.I)

# UN Comtrade bulk-download column names this adapter recognizes, plus a
# small set of common export-tool variants. Aliasing is deliberately
# narrow: an unrecognized column is left absent (never guessed at) rather
# than silently mapped to the wrong field.
_FIELD_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("reporter_country", ("reporterISO", "reporterDesc", "reporterCode", "reporter")),
    ("partner_country", ("partnerISO", "partnerDesc", "partnerCode", "partner")),
    ("hs_code", ("cmdCode", "commodityCode", "hs_code", "hsCode")),
    ("period", ("period", "refPeriodId", "year")),
    ("trade_value", ("primaryValue", "TradeValue", "trade_value")),
    ("net_weight", ("netWgt", "NetWeight", "net_weight")),
    ("quantity", ("qty", "Qty", "quantity")),
    ("quantity_unit", ("qtyUnitAbbr", "QtyUnitAbbr", "quantity_unit")),
    ("flow_direction", ("flowDesc", "flowCode", "flow_direction")),
)


class TradeFlowImportError(ValueError):
    pass


def validate_input_path(path: str | Path) -> Path:
    candidate = Path(path)
    if ".." in candidate.parts:
        raise TradeFlowImportError("path traversal is not allowed")
    if candidate.suffix.lower() not in {".json", ".csv"}:
        raise TradeFlowImportError("only sanitized JSON and CSV inputs are supported")
    if not candidate.is_file():
        raise TradeFlowImportError("trade-flow import file does not exist")
    if candidate.stat().st_size > MAX_BULK_FILE_BYTES:
        raise TradeFlowImportError(f"trade-flow import file exceeds {MAX_BULK_FILE_BYTES} bytes")
    return candidate


def contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SECRET_KEY.search(str(key)) or contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item) for item in value)
    return bool(SECRET_VALUE.search(str(value))) if value is not None else False


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
    return bool(HTML_MARKERS.search(text))


def _reject_raw_html(value: Any) -> None:
    if contains_html(value):
        raise TradeFlowImportError("raw HTML is not allowed")


def _read_import_text(path: str | Path, *, encoding: str = "utf-8") -> str:
    target = validate_input_path(path)
    raw_bytes = target.read_bytes()
    _reject_raw_html(raw_bytes)
    text = raw_bytes.decode(encoding)
    _reject_raw_html(text)
    return text


def _value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def _apply_aliases(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for canonical, aliases in _FIELD_ALIASES:
        value = _value(row, *aliases)
        if value is not None:
            result[canonical] = value
    return result


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_record(row: Mapping[str, Any], *, mode: str = "fixture") -> dict[str, Any] | None:
    """Normalize one UN Comtrade-shaped row into a plain, sanitized dict.

    Returns ``None`` for a row missing both a reporter and a partner
    country (nothing usable to normalize). Every numeric field a caller
    might expect (``trade_value``, ``quantity``) is ``None`` when absent
    from the row -- never defaulted to ``0`` -- so the missing-versus-
    explicit-zero distinction survives into
    ``services.geographic_opportunity``'s own dataclasses.
    """
    if not isinstance(row, Mapping):
        return None
    _reject_raw_html(row)
    if contains_secret(row):
        return None
    aliased = _apply_aliases(row)
    reporter = str(aliased.get("reporter_country", "") or "").strip()
    partner = str(aliased.get("partner_country", "") or "").strip()
    if not reporter and not partner:
        return None
    warnings: list[str] = []
    trade_value = _number(aliased.get("trade_value"))
    if trade_value is None:
        warnings.append("trade_value_unavailable")
    quantity = _number(aliased.get("quantity"))
    if quantity is None:
        warnings.append("quantity_unavailable")
    currency = str(_value(row, "currency", "priceUnit") or "").strip()
    if not currency:
        # UN Comtrade's primaryValue is documented as USD-denominated in
        # the bulk-download files this adapter targets; a caller must
        # still confirm this explicitly (this adapter marks it as
        # assumed, never silent) before treating it as USD with any FX
        # provenance.
        currency = "USD"
        warnings.append("currency_assumed_usd_per_comtrade_convention")
    return {
        "source": PINNED_SOURCE,
        "mode": mode,
        "reporter_country": reporter,
        "partner_country": partner,
        "hs_code": str(aliased.get("hs_code", "") or "").strip(),
        "period": str(aliased.get("period", "") or "").strip(),
        "flow_direction": str(aliased.get("flow_direction", "") or "").strip(),
        "trade_value": trade_value,
        "currency": currency,
        "quantity": quantity,
        "quantity_unit": str(aliased.get("quantity_unit", "") or "").strip(),
        "warnings": tuple(sorted(set(warnings))),
    }


def _rows_from_json(path: str | Path) -> list[Mapping[str, Any]]:
    raw = json.loads(_read_import_text(path))
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, Mapping)]
    if isinstance(raw, Mapping):
        for key in ("data", "dataset", "records"):
            if isinstance(raw.get(key), list):
                return [item for item in raw[key] if isinstance(item, Mapping)]
        return [raw]
    return []


def import_json(path: str | Path, *, mode: str = "fixture") -> list[dict[str, Any]]:
    records = [normalize_record(row, mode=mode) for row in _rows_from_json(path)]
    return [record for record in records if record is not None]


def import_csv(path: str | Path, *, mode: str = "manual_import") -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(_read_import_text(path, encoding="utf-8-sig"))))
    records = [normalize_record(row, mode=mode) for row in rows]
    return [record for record in records if record is not None]


def _client_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY.search(str(key)):
                continue
            if isinstance(item, str) and HTML_MARKERS.search(item):
                continue
            cleaned[str(key)] = _client_safe_value(item)
        return cleaned
    if isinstance(value, list):
        return [_client_safe_value(item) for item in value]
    return value


def client_safe_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Importer-safe projection of one normalized record."""
    return _client_safe_value(dict(record))


def import_un_comtrade_bulk_file(path: str | Path) -> list[dict[str, Any]]:
    """The one caller-facing entrypoint: reads a manually downloaded UN
    Comtrade bulk-download file (JSON or CSV) from local disk and
    returns normalized, sanitized records. Never calls
    ``comtradeapi.un.org`` or any other live endpoint."""
    target = validate_input_path(path)
    if target.suffix.lower() == ".csv":
        return import_csv(target)
    return import_json(target)
