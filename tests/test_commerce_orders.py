"""Tests for backend.commerce.orders — ingest_order/_run_side_effects/reverse_order.

Covers the Tier 1 money-safety fixes: a DB write failure during ingest
surfaces as an error (not a swallowed exception), and a crash between
record_order() succeeding and the ROAS/LTV/journal side effects completing
self-heals on retry instead of silently skipping those side effects forever.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


@pytest.fixture
def repo(monkeypatch, tmp_path):
    from backend.data.repositories.order_repository import OrderRepository
    import backend.commerce.orders as orders_mod
    import backend.data.repositories.order_repository as repo_mod

    r = OrderRepository(db_path=str(tmp_path / "orders.db"))
    monkeypatch.setattr(repo_mod, "order_repository", r)
    monkeypatch.setattr(orders_mod, "_roas_repo", None)

    from backend.data.repositories.roas_repository import RoasRepository
    monkeypatch.setattr(orders_mod, "_roas_repo",
                        RoasRepository(db_path=str(tmp_path / "roas.db")))

    from backend.economics.ltv import CohortTracker
    import backend.economics.ltv as ltv_mod
    monkeypatch.setattr(ltv_mod, "cohort_tracker", CohortTracker())

    return r


def _payload(order_id="order_1", amount=19.99, payment_intent_id=""):
    return {
        "order_id": order_id, "brand_id": "beauty", "product_id": "jade-roller",
        "qty": 1, "amount": amount, "currency": "usd",
        "customer": {"email": "buyer@example.com", "name": "Buyer",
                    "shipping": {"city": "Austin"}},
        "utm": {"utm_source": "tiktok"},
        "payment_intent_id": payment_intent_id,
    }


class TestIngestOrder:
    def test_records_customer_and_order(self, repo):
        from backend.commerce.orders import ingest_order

        result = ingest_order("stripe", _payload())
        assert result["status"] == "ok"
        assert result["is_new"] is True

        order = repo.get_order("order_1")
        assert order is not None
        assert order.amount == 19.99
        assert order.side_effects_done is True

    def test_record_failure_returns_error_not_exception(self, repo, monkeypatch):
        from backend.commerce.orders import ingest_order

        monkeypatch.setattr(repo, "record_order",
                            lambda order: (_ for _ in ()).throw(RuntimeError("db locked")))
        result = ingest_order("stripe", _payload())
        assert result["status"] == "error"
        assert repo.get_order("order_1") is None

    def test_side_effects_retry_after_partial_crash_self_heals(self, repo, monkeypatch):
        """Simulates a crash between record_order() succeeding and the three
        side-effect feeds completing: the first ingest_order call fails
        mid-way (journal raises), so side_effects_done stays False; a
        webhook retry (second ingest_order call for the same order_id) must
        still complete the feeds rather than skipping them because
        is_new=False."""
        import backend.commerce.orders as orders_mod

        call_count = {"n": 0}
        original_journal = orders_mod._journal_order_received

        def flaky_journal(order):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("event_store append failed")
            return original_journal(order)

        monkeypatch.setattr(orders_mod, "_journal_order_received", flaky_journal)

        from backend.commerce.orders import ingest_order

        result1 = ingest_order("stripe", _payload())
        assert result1["status"] == "ok"
        assert result1["is_new"] is True
        order_after_first = repo.get_order("order_1")
        assert order_after_first.side_effects_done is False, (
            "journal failure should have prevented marking side effects done"
        )

        result2 = ingest_order("stripe", _payload())
        assert result2["status"] == "ok"
        assert result2["is_new"] is False  # order_id already recorded — this is a retry
        order_after_second = repo.get_order("order_1")
        assert order_after_second.side_effects_done is True, (
            "retry should have completed the side effects that never finished"
        )

        # LTV cohort tracker must not double-count the same order across the
        # failed-then-retried attempts. (No catalog entry is registered in
        # this fixture, so _feed_ltv's category lookup falls back to "general".)
        from backend.economics.ltv import cohort_tracker
        assert cohort_tracker._total_counts.get("general", 0) == 1

    def test_missing_order_id_is_an_error(self, repo):
        from backend.commerce.orders import ingest_order
        result = ingest_order("stripe", {"amount": 10.0})
        assert result["status"] == "error"
        assert result["error"] == "missing_order_id"


class TestReverseOrder:
    def test_reverses_received_order_to_refunded(self, repo):
        from backend.commerce.orders import ingest_order, reverse_order

        ingest_order("stripe", _payload())
        result = reverse_order("order_1", reason="charge.refunded")
        assert result["status"] == "ok"
        assert result["fulfillment_status"] == "REFUNDED"

        order = repo.get_order("order_1")
        assert order.fulfillment_status == "REFUNDED"

    def test_reverses_shipped_order_to_refunded(self, repo):
        """A refund/chargeback can arrive well after the order shipped —
        REFUNDED must be reachable from PLACED/SHIPPED/DELIVERED too, not
        just RECEIVED."""
        from backend.commerce.orders import ingest_order, reverse_order

        ingest_order("stripe", _payload())
        repo.update_fulfillment("order_1", "PLACED")
        repo.update_fulfillment("order_1", "SHIPPED")

        result = reverse_order("order_1", reason="charge.refunded")
        assert result["status"] == "ok"
        assert repo.get_order("order_1").fulfillment_status == "REFUNDED"

    def test_unknown_order_is_an_error(self, repo):
        from backend.commerce.orders import reverse_order
        result = reverse_order("nonexistent", reason="charge.refunded")
        assert result["status"] == "error"
        assert result["error"] == "unknown_order"

    def test_already_refunded_order_is_an_illegal_transition(self, repo):
        from backend.commerce.orders import ingest_order, reverse_order

        ingest_order("stripe", _payload())
        reverse_order("order_1", reason="charge.refunded")
        result = reverse_order("order_1", reason="charge.refunded")
        assert result["status"] == "error"
        assert result["error"] == "illegal_transition"

    def test_compensating_negative_roas_entry_recorded(self, repo):
        import sqlite3
        from backend.commerce.orders import ingest_order, reverse_order, _get_roas_repo

        ingest_order("stripe", _payload(amount=25.0))
        reverse_order("order_1", reason="charge.refunded")

        roas_repo = _get_roas_repo()
        conn = sqlite3.connect(roas_repo.db_path)
        row = conn.execute(
            "SELECT total_price FROM orders WHERE id = ?", ("refund_order_1",)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == -25.0
