"""Commerce order + customer repository (the money path's system of record).

Stores customers (with shipping address — needed to forward orders to
dropship suppliers), commerce orders with their fulfillment lifecycle, and
a webhook-event dedupe ledger so Stripe/Shopify retries are idempotent.

Mirrors roas_repository.py's sqlite3-at-data/marketos.db idiom.

Fulfillment lifecycle:
    RECEIVED -> PLACED -> SHIPPED -> DELIVERED
                    \\-> FAILED        (supplier rejection / error)
    RECEIVED -> REFUNDED               (cancellation before placement)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

FULFILLMENT_STATES = ["RECEIVED", "PLACED", "SHIPPED", "DELIVERED", "FAILED", "REFUNDED"]

_VALID_TRANSITIONS = {
    "RECEIVED": {"PLACED", "FAILED", "REFUNDED"},
    "PLACED": {"SHIPPED", "DELIVERED", "FAILED"},
    "SHIPPED": {"DELIVERED", "FAILED"},
    "DELIVERED": set(),
    "FAILED": {"PLACED"},          # retry after failure is allowed
    "REFUNDED": set(),
}


@dataclass
class CustomerRecord:
    customer_id: str               # stable id (email hash or platform id)
    email: str
    name: str = ""
    shipping: dict = field(default_factory=dict)  # {line1, line2, city, state, postal_code, country}
    first_seen: str = ""

    def __post_init__(self):
        if not self.first_seen:
            self.first_seen = datetime.now(timezone.utc).isoformat()


@dataclass
class CommerceOrder:
    order_id: str
    source: str                    # "stripe" | "shopify" | "manual"
    brand_id: str
    product_id: str
    qty: int
    amount: float                  # gross amount collected, in currency units
    currency: str
    customer_id: str
    utm: dict = field(default_factory=dict)
    fulfillment_status: str = "RECEIVED"
    supplier_name: str = ""
    supplier_order_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class OrderRepository:
    """Customers + commerce orders + webhook dedupe, in data/marketos.db."""

    def __init__(self, db_path: str = "data/marketos.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY,
                    email TEXT,
                    name TEXT,
                    shipping_json TEXT,
                    first_seen TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commerce_orders (
                    order_id TEXT PRIMARY KEY,
                    source TEXT,
                    brand_id TEXT,
                    product_id TEXT,
                    qty INTEGER,
                    amount REAL,
                    currency TEXT,
                    customer_id TEXT,
                    utm_json TEXT,
                    fulfillment_status TEXT,
                    supplier_name TEXT,
                    supplier_order_id TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    source TEXT,
                    ts TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    # ── webhook dedupe ───────────────────────────────────────────────────

    def mark_event_seen(self, event_id: str, source: str = "") -> bool:
        """Record a webhook event id. Returns False if already seen (duplicate)."""
        if not event_id:
            return True
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO webhook_events (event_id, source, ts) VALUES (?, ?, ?)",
                (event_id, source, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    # ── customers ────────────────────────────────────────────────────────

    def upsert_customer(self, customer: CustomerRecord) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO customers (customer_id, email, name, shipping_json, first_seen)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(customer_id) DO UPDATE SET
                     email=excluded.email,
                     name=CASE WHEN excluded.name != '' THEN excluded.name ELSE customers.name END,
                     shipping_json=CASE WHEN excluded.shipping_json != '{}'
                                        THEN excluded.shipping_json
                                        ELSE customers.shipping_json END""",
                (customer.customer_id, customer.email, customer.name,
                 json.dumps(customer.shipping), customer.first_seen),
            )
            conn.commit()
        finally:
            conn.close()

    def get_customer(self, customer_id: str) -> CustomerRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT customer_id, email, name, shipping_json, first_seen "
                "FROM customers WHERE customer_id = ?", (customer_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return CustomerRecord(
            customer_id=row[0], email=row[1] or "", name=row[2] or "",
            shipping=json.loads(row[3] or "{}"), first_seen=row[4] or "",
        )

    # ── orders ───────────────────────────────────────────────────────────

    def record_order(self, order: CommerceOrder) -> bool:
        """Insert an order. Returns False if the order_id already exists."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO commerce_orders
                   (order_id, source, brand_id, product_id, qty, amount, currency,
                    customer_id, utm_json, fulfillment_status, supplier_name,
                    supplier_order_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order.order_id, order.source, order.brand_id, order.product_id,
                 order.qty, order.amount, order.currency, order.customer_id,
                 json.dumps(order.utm), order.fulfillment_status,
                 order.supplier_name, order.supplier_order_id,
                 order.created_at, order.updated_at),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_order(self, order_id: str) -> CommerceOrder | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT order_id, source, brand_id, product_id, qty, amount, currency, "
                "customer_id, utm_json, fulfillment_status, supplier_name, "
                "supplier_order_id, created_at, updated_at "
                "FROM commerce_orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        finally:
            conn.close()
        return self._row_to_order(row) if row else None

    def orders_by_status(self, status: str, limit: int = 100) -> list[CommerceOrder]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT order_id, source, brand_id, product_id, qty, amount, currency, "
                "customer_id, utm_json, fulfillment_status, supplier_name, "
                "supplier_order_id, created_at, updated_at "
                "FROM commerce_orders WHERE fulfillment_status = ? "
                "ORDER BY created_at LIMIT ?", (status, limit)
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_order(r) for r in rows]

    def update_fulfillment(self, order_id: str, status: str,
                           supplier_name: str | None = None,
                           supplier_order_id: str | None = None) -> bool:
        """Advance an order's fulfillment state (validated against the
        transition table). Returns False on unknown order or illegal move."""
        if status not in FULFILLMENT_STATES:
            return False
        order = self.get_order(order_id)
        if order is None:
            return False
        if status not in _VALID_TRANSITIONS.get(order.fulfillment_status, set()):
            _log.warning("illegal_fulfillment_transition order=%s %s->%s",
                         order_id, order.fulfillment_status, status)
            return False

        conn = self._connect()
        try:
            conn.execute(
                """UPDATE commerce_orders SET
                     fulfillment_status = ?,
                     supplier_name = COALESCE(?, supplier_name),
                     supplier_order_id = COALESCE(?, supplier_order_id),
                     updated_at = ?
                   WHERE order_id = ?""",
                (status, supplier_name, supplier_order_id,
                 datetime.now(timezone.utc).isoformat(), order_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def _row_to_order(row) -> CommerceOrder:
        return CommerceOrder(
            order_id=row[0], source=row[1] or "", brand_id=row[2] or "",
            product_id=row[3] or "", qty=int(row[4] or 1),
            amount=float(row[5] or 0.0), currency=row[6] or "usd",
            customer_id=row[7] or "", utm=json.loads(row[8] or "{}"),
            fulfillment_status=row[9] or "RECEIVED",
            supplier_name=row[10] or "", supplier_order_id=row[11] or "",
            created_at=row[12] or "", updated_at=row[13] or "",
        )


# Module singleton (same pattern as the other repositories)
order_repository = OrderRepository()
