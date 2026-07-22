"""backend.commerce.brands — the brand registry.

A Brand is a category-focused storefront identity: "the handful of them"
the system hosts, each with its own landing site (default) or Shopify
binding, channel preferences for organic/paid marketing, and preferred
suppliers. Products are routed to a brand by category; a new brand is
auto-created per category up to MAX_BRANDS, after which everything else
lands on the default general brand.

Persistence: state/brands.json via the shared save_json_atomic idiom
(PatternStore/PlaybookMemory-style snapshot/restore, restored on import).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)

_BRANDS_FILE = "brands.json"
_MAX_BRANDS = int(os.getenv("MAX_BRANDS", "5"))

_DEFAULT_BRAND_ID = "default"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "brand"


@dataclass
class Brand:
    brand_id: str
    name: str
    category: str
    tagline: str = ""
    # Organic/paid channel preferences, e.g. {"tiktok": 0.6, "meta": 0.4}.
    # Empty dict = defer to the channel selector / legacy split.
    channel_preferences: dict = field(default_factory=dict)
    storefront: str = "landing"          # "landing" | "shopify"
    supplier_bindings: list = field(default_factory=list)  # supplier names, priority order
    active: bool = True
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


class BrandRegistry:
    """Thread-safe registry of the hosted brands, persisted across restarts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._brands: dict[str, Brand] = {}
        self._category_index: dict[str, str] = {}  # category -> brand_id

    # ── CRUD ────────────────────────────────────────────────────────────

    def get(self, brand_id: str) -> Brand | None:
        with self._lock:
            return self._brands.get(brand_id)

    def all(self) -> list[Brand]:
        with self._lock:
            return list(self._brands.values())

    def upsert(self, brand: Brand) -> None:
        with self._lock:
            self._brands[brand.brand_id] = brand
            if brand.category:
                self._category_index.setdefault(brand.category, brand.brand_id)
        self._persist()

    # ── category routing ────────────────────────────────────────────────

    def resolve_for_category(self, category: str) -> Brand:
        """Return the brand owning *category*, creating one if room remains.

        Routing rules:
          1. A brand already owns the category -> that brand.
          2. Fewer than MAX_BRANDS exist (excluding default) -> auto-create a
             category brand and assign it.
          3. Otherwise -> the default general brand (seeded on first use).
        """
        category = (category or "general").strip().lower()

        with self._lock:
            owner_id = self._category_index.get(category)
            if owner_id and owner_id in self._brands:
                return self._brands[owner_id]

            non_default = [b for b in self._brands.values()
                           if b.brand_id != _DEFAULT_BRAND_ID]
            if category != "general" and len(non_default) < _MAX_BRANDS:
                brand = Brand(
                    brand_id=_slugify(category),
                    name=f"{category.title()} Collective",
                    category=category,
                    tagline=f"Curated {category} finds, shipped to your door.",
                )
                self._brands[brand.brand_id] = brand
                self._category_index[category] = brand.brand_id
                _log.info("brand_auto_created brand=%s category=%s", brand.brand_id, category)
                created = brand
            else:
                created = self._ensure_default_locked()
                self._category_index.setdefault(category, created.brand_id)

        self._persist()
        return created

    def _ensure_default_locked(self) -> Brand:
        """Caller must hold the lock."""
        brand = self._brands.get(_DEFAULT_BRAND_ID)
        if brand is None:
            brand = Brand(
                brand_id=_DEFAULT_BRAND_ID,
                name="Everyday Finds",
                category="general",
                tagline="Products people are talking about.",
            )
            self._brands[_DEFAULT_BRAND_ID] = brand
            self._category_index.setdefault("general", _DEFAULT_BRAND_ID)
        return brand

    def ensure_default(self) -> Brand:
        with self._lock:
            brand = self._ensure_default_locked()
        self._persist()
        return brand

    # ── persistence ─────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "brands": [asdict(b) for b in self._brands.values()],
                "category_index": dict(self._category_index),
            }

    def restore(self, data: dict) -> None:
        with self._lock:
            self._brands = {
                row["brand_id"]: Brand(**row)
                for row in data.get("brands", [])
                if row.get("brand_id")
            }
            self._category_index = {
                str(k): str(v) for k, v in data.get("category_index", {}).items()
            }

    def _persist(self) -> None:
        save_json_atomic(state_path(_BRANDS_FILE), self.snapshot())

    def reset(self) -> None:
        """Test helper — clear all brands."""
        with self._lock:
            self._brands.clear()
            self._category_index.clear()


brand_registry = BrandRegistry()


def _load_on_import() -> None:
    data = load_json(state_path(_BRANDS_FILE))
    if data:
        brand_registry.restore(data)
        _log.info("brand_registry_loaded brands=%d", len(brand_registry.all()))


_load_on_import()
