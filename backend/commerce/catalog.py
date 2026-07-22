"""backend.commerce.catalog — per-brand product catalog.

The catalog is the single source of truth for what each brand currently
sells: retail price, supplier binding, landed cost, live/paused status and
stock health. The storefront layer renders from it; the inventory
reconciler updates it; order ingestion joins against it.

Persistence: state/catalog.json (save_json_atomic snapshot idiom).
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)

_CATALOG_FILE = "catalog.json"

STATUS_DRAFT = "draft"
STATUS_LIVE = "live"
STATUS_PAUSED = "paused"
_VALID_STATUSES = {STATUS_DRAFT, STATUS_LIVE, STATUS_PAUSED}


def product_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "product"


@dataclass
class CatalogEntry:
    product_id: str            # slug, unique within the catalog
    brand_id: str
    title: str
    retail_price: float
    supplier: str = ""         # supplier name (matches SupplierQuote.supplier)
    supplier_product_id: str = ""
    landed_cost: float = 0.0
    status: str = STATUS_DRAFT
    stock_ok: bool = True
    page_url: str = ""
    description_html: str = ""
    bullets: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class ProductCatalog:
    """Thread-safe catalog keyed by product_id, persisted across restarts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[str, CatalogEntry] = {}

    def register(self, entry: CatalogEntry) -> CatalogEntry:
        with self._lock:
            self._entries[entry.product_id] = entry
        self._persist()
        return entry

    def get(self, product_id: str) -> CatalogEntry | None:
        with self._lock:
            return self._entries.get(product_id)

    def update(self, product_id: str, **fields) -> CatalogEntry | None:
        """Update mutable fields; returns the updated entry or None."""
        with self._lock:
            entry = self._entries.get(product_id)
            if entry is None:
                return None
            for key, value in fields.items():
                if key == "status" and value not in _VALID_STATUSES:
                    continue
                if hasattr(entry, key) and key not in ("product_id", "created_at"):
                    setattr(entry, key, value)
            entry.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist()
        return entry

    def for_brand(self, brand_id: str, status: str | None = None) -> list[CatalogEntry]:
        with self._lock:
            entries = [e for e in self._entries.values() if e.brand_id == brand_id]
        if status:
            entries = [e for e in entries if e.status == status]
        return sorted(entries, key=lambda e: e.created_at)

    def all(self) -> list[CatalogEntry]:
        with self._lock:
            return list(self._entries.values())

    # ── persistence ─────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {"entries": [asdict(e) for e in self._entries.values()]}

    def restore(self, data: dict) -> None:
        with self._lock:
            self._entries = {
                row["product_id"]: CatalogEntry(**row)
                for row in data.get("entries", [])
                if row.get("product_id")
            }

    def _persist(self) -> None:
        save_json_atomic(state_path(_CATALOG_FILE), self.snapshot())

    def reset(self) -> None:
        """Test helper — clear the catalog."""
        with self._lock:
            self._entries.clear()


product_catalog = ProductCatalog()


def _load_on_import() -> None:
    data = load_json(state_path(_CATALOG_FILE))
    if data:
        product_catalog.restore(data)
        _log.info("product_catalog_loaded entries=%d", len(product_catalog.all()))


_load_on_import()
