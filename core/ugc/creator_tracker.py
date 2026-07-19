"""core.ugc.creator_tracker — seeded creator-to-product-to-revenue tracking.

Minimal viable tracker: record which creators were sent product at what cost,
track resulting organic orders attributed back to them, and compute cost per
organic order. This enables:
- Identifying high-performing creators for repeat seeding
- Measuring organic channel ROI (cost-per-order from seeding)
- Comparing to paid CAC as a go/no-go gate for organic scaling
- Building a creator pool for future product launches
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone


class CreatorSeed:
    """Single seeding event: creator → product → cost + tracked results."""

    def __init__(
        self,
        creator_id: str,
        product_id: str,
        seeding_cost: float = 0.0,
        sent_date: float | None = None,
    ):
        self.creator_id = creator_id
        self.product_id = product_id
        self.seeding_cost = seeding_cost
        self.sent_date = sent_date or datetime.now(timezone.utc).timestamp()
        # Tracking fields (updated as orders come in)
        self.organic_orders_attributed = 0
        self.organic_revenue = 0.0
        self.last_order_ts = self.sent_date

    def add_organic_order(self, order_value: float = 0.0, ts: float | None = None) -> None:
        """Record one organic order attributed to this creator seed."""
        self.organic_orders_attributed += 1
        self.organic_revenue += order_value
        self.last_order_ts = ts or datetime.now(timezone.utc).timestamp()

    def to_dict(self) -> dict:
        """Serialize for storage."""
        return {
            "creator_id": self.creator_id,
            "product_id": self.product_id,
            "seeding_cost": round(self.seeding_cost, 2),
            "sent_date": self.sent_date,
            "organic_orders_attributed": self.organic_orders_attributed,
            "organic_revenue": round(self.organic_revenue, 2),
            "last_order_ts": self.last_order_ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CreatorSeed:
        """Deserialize from storage."""
        seed = cls(
            creator_id=data["creator_id"],
            product_id=data["product_id"],
            seeding_cost=data.get("seeding_cost", 0.0),
            sent_date=data.get("sent_date"),
        )
        seed.organic_orders_attributed = data.get("organic_orders_attributed", 0)
        seed.organic_revenue = data.get("organic_revenue", 0.0)
        seed.last_order_ts = data.get("last_order_ts", seed.sent_date)
        return seed


class CreatorTracker:
    """Minimal tracker for creator seeding events and organic attribution.

    Schema: (creator_id, product_id) → CreatorSeed
           (creator_id) → list[CreatorSeed] (all seedings by creator)
           (product_id) → list[CreatorSeed] (all seeders for product)
    """

    def __init__(self):
        # (creator_id, product_id) → CreatorSeed
        self._seeds: dict[tuple[str, str], CreatorSeed] = {}
        # creator_id → list of CreatorSeeds
        self._creator_index: dict[str, list[CreatorSeed]] = defaultdict(list)
        # product_id → list of CreatorSeeds
        self._product_index: dict[str, list[CreatorSeed]] = defaultdict(list)

    def record_seed(
        self,
        creator_id: str,
        product_id: str,
        seeding_cost: float = 0.0,
        sent_date: float | None = None,
    ) -> CreatorSeed:
        """Record a creator seeding event (product sent to creator)."""
        key = (creator_id, product_id)
        if key not in self._seeds:
            seed = CreatorSeed(creator_id, product_id, seeding_cost, sent_date)
            self._seeds[key] = seed
            self._creator_index[creator_id].append(seed)
            self._product_index[product_id].append(seed)
        return self._seeds[key]

    def add_organic_order(
        self,
        creator_id: str,
        product_id: str,
        order_value: float = 0.0,
        ts: float | None = None,
    ) -> None:
        """Record an organic order attributed to a creator-product seed."""
        key = (creator_id, product_id)
        if key in self._seeds:
            self._seeds[key].add_organic_order(order_value, ts)

    def get_seed(self, creator_id: str, product_id: str) -> CreatorSeed | None:
        """Get a specific seed."""
        return self._seeds.get((creator_id, product_id))

    def creator_stats(self, creator_id: str) -> dict:
        """Aggregate stats for a creator across all seeded products.

        Returns: {
            total_seeds: int,
            total_seeding_cost: float,
            total_organic_orders: int,
            total_organic_revenue: float,
            avg_cost_per_order: float,
            avg_revenue_per_order: float,
        }
        """
        seeds = self._creator_index.get(creator_id, [])
        if not seeds:
            return {
                "total_seeds": 0,
                "total_seeding_cost": 0.0,
                "total_organic_orders": 0,
                "total_organic_revenue": 0.0,
                "avg_cost_per_order": 0.0,
                "avg_revenue_per_order": 0.0,
            }

        total_cost = sum(s.seeding_cost for s in seeds)
        total_orders = sum(s.organic_orders_attributed for s in seeds)
        total_revenue = sum(s.organic_revenue for s in seeds)

        avg_cost_per = total_cost / total_orders if total_orders > 0 else 0.0
        avg_rev_per = total_revenue / total_orders if total_orders > 0 else 0.0

        return {
            "total_seeds": len(seeds),
            "total_seeding_cost": round(total_cost, 2),
            "total_organic_orders": total_orders,
            "total_organic_revenue": round(total_revenue, 2),
            "avg_cost_per_order": round(avg_cost_per, 2),
            "avg_revenue_per_order": round(avg_rev_per, 2),
        }

    def product_stats(self, product_id: str) -> dict:
        """Aggregate stats for a product across all seeded creators.

        Returns similar to creator_stats but for all creators seeding the product.
        """
        seeds = self._product_index.get(product_id, [])
        if not seeds:
            return {
                "total_seeders": 0,
                "total_seeding_cost": 0.0,
                "total_organic_orders": 0,
                "total_organic_revenue": 0.0,
                "avg_cost_per_order": 0.0,
                "avg_revenue_per_order": 0.0,
            }

        total_cost = sum(s.seeding_cost for s in seeds)
        total_orders = sum(s.organic_orders_attributed for s in seeds)
        total_revenue = sum(s.organic_revenue for s in seeds)

        avg_cost_per = total_cost / total_orders if total_orders > 0 else 0.0
        avg_rev_per = total_revenue / total_orders if total_orders > 0 else 0.0

        return {
            "total_seeders": len(seeds),
            "total_seeding_cost": round(total_cost, 2),
            "total_organic_orders": total_orders,
            "total_organic_revenue": round(total_revenue, 2),
            "avg_cost_per_order": round(avg_cost_per, 2),
            "avg_revenue_per_order": round(avg_rev_per, 2),
        }

    def top_creators(self, n: int = 5, by: str = "avg_cost_per_order") -> list[tuple[str, dict]]:
        """Return top N creators ranked by metric (avg_cost_per_order, total_organic_revenue, etc).

        Returns: [(creator_id, stats_dict), ...]
        """
        all_creators = []
        for creator_id in self._creator_index.keys():
            stats = self.creator_stats(creator_id)
            all_creators.append((creator_id, stats))

        # Sort by specified metric (lower cost-per-order is better, higher revenue is better)
        if by == "avg_cost_per_order":
            sorted_creators = sorted(all_creators, key=lambda x: x[1].get(by, float("inf")))
        elif by in ["total_organic_revenue", "total_organic_orders"]:
            sorted_creators = sorted(all_creators, key=lambda x: x[1].get(by, 0), reverse=True)
        else:
            sorted_creators = sorted(all_creators, key=lambda x: x[0])

        return sorted_creators[:n]

    def all_seeds_as_dicts(self) -> list[dict]:
        """Export all seeds for persistence."""
        return [seed.to_dict() for seed in self._seeds.values()]

    def restore_from_dicts(self, seeds_data: list[dict]) -> None:
        """Restore seeds from persisted data."""
        self._seeds.clear()
        self._creator_index.clear()
        self._product_index.clear()

        for data in seeds_data:
            seed = CreatorSeed.from_dict(data)
            key = (seed.creator_id, seed.product_id)
            self._seeds[key] = seed
            self._creator_index[seed.creator_id].append(seed)
            self._product_index[seed.product_id].append(seed)


# Module singleton
creator_tracker = CreatorTracker()
