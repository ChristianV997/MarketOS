#!/usr/bin/env python3
"""scripts/ingest_category_priors.py — turn downloaded public datasets into
backend/data/seed/category_priors.json.

Offline, run manually — never invoked at runtime. Requires the datasets
downloaded to local disk first (this script itself makes no network calls):

  Amazon Reviews 2023 (McAuley-Lab, HuggingFace) — per-category metadata:
    pip install datasets
    python -c "
from datasets import load_dataset
load_dataset('McAuley-Lab/Amazon-Reviews-2023', 'raw_meta_Pet_Supplies',
             trust_remote_code=True)['full'].save_to_disk(
    'data/amazon_reviews_2023/raw_meta_Pet_Supplies')
"
    (repeat per category of interest — e.g. raw_meta_Baby_Products,
     raw_meta_Beauty_and_Personal_Care, raw_meta_Electronics; the full
     config list is at https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023)

  Olist Brazilian E-Commerce (Kaggle) — 100k real orders:
    kaggle datasets download -d olistbr/brazilian-ecommerce \
      -p data/olist --unzip

  Wish Summer Products (Kaggle, jmmvutu/summer-products-and-sales-in-
  ecommerce-wish) — real sales-velocity + rating + merchant data:
    kaggle datasets download \
      -d jmmvutu/summer-products-and-sales-in-ecommerce-wish \
      -p data/wish --unzip

    Unlike Amazon/Olist, this dataset has no product-category column —
    it's inherently a single-niche ("summer products") export, so every
    row is bucketed under one category key: "wish_summer_products". A
    user wanting a finer split could bucket by the dataset's own free-text
    `tags` column before calling wish_category_stats(), but that's out of
    scope here — see wish_category_stats()'s docstring.

Usage:
    python scripts/ingest_category_priors.py \
        --amazon-dir data/amazon_reviews_2023 \
        --amazon-categories raw_meta_Pet_Supplies,raw_meta_Baby_Products \
        --olist-dir data/olist \
        --wish-csv data/wish/summer-products-with-rating-and-performance_2020-08.csv \
        --out backend/data/seed/category_priors.json

The four transform functions below (amazon_category_stats,
olist_category_stats, wish_category_stats, merge_priors) are pure — no
filesystem or network access — and are exercised in
tests/test_ingest_category_priors.py on inline fixtures; only the loader
helpers and main() touch real files, and only when this script is
actually run with real downloaded data.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

# A repeat is a second order from the same customer within this window —
# matches backend.economics.ltv.REPEAT_WINDOW_DAYS so the ingested prior is
# on the same footing as the live-observed repeat rate it seeds/blends with.
_REPEAT_WINDOW_DAYS = 60


def amazon_category_stats(rows: list[dict]) -> dict[str, Any]:
    """Pure transform: Amazon Reviews 2023 metadata rows (each at least
    {"price": float|None, "average_rating": float|None}) ->
    {price_band, rating_mean, review_volume, return_proxy}.

    return_proxy is the share of ratings <= 2 stars — Amazon doesn't
    publish return rates directly, so low-rating share is used as a
    return-risk proxy (a product with a lot of 1-2 star reviews plausibly
    has a return/refund rate above category baseline).
    """
    prices = sorted(r["price"] for r in rows if r.get("price") is not None and r["price"] > 0)
    ratings = [r["average_rating"] for r in rows if r.get("average_rating") is not None]
    low_ratings = [r for r in ratings if r <= 2.0]

    def _percentile(sorted_vals: list[float], p: float) -> float | None:
        if not sorted_vals:
            return None
        idx = min(len(sorted_vals) - 1, max(0, round(p * (len(sorted_vals) - 1))))
        return round(sorted_vals[idx], 2)

    return {
        "price_band": {
            "p25": _percentile(prices, 0.25),
            "p50": _percentile(prices, 0.50),
            "p75": _percentile(prices, 0.75),
        },
        "rating_mean": round(sum(ratings) / len(ratings), 3) if ratings else None,
        "review_volume": len(rows),
        "return_proxy": round(len(low_ratings) / len(ratings), 4) if ratings else None,
    }


def olist_category_stats(orders: list[dict]) -> dict[str, Any]:
    """Pure transform: Olist order rows (each at least {"customer_unique_id":
    str, "order_purchase_timestamp": unix seconds, "delivery_days": int|None})
    -> {repeat_rate, delivery_days_p50, order_volume}.

    repeat_rate = share of distinct customers who placed a second order
    within _REPEAT_WINDOW_DAYS of a prior one (not share of orders that
    were repeats — customer-level, matching how
    backend.economics.ltv.CohortTracker defines the signal).
    """
    from collections import defaultdict

    by_customer: dict[str, list[float]] = defaultdict(list)
    for o in orders:
        customer = o.get("customer_unique_id")
        ts = o.get("order_purchase_timestamp")
        if customer and ts is not None:
            by_customer[customer].append(float(ts))

    repeat_customers = 0
    for timestamps in by_customer.values():
        timestamps.sort()
        for i in range(1, len(timestamps)):
            if (timestamps[i] - timestamps[i - 1]) <= _REPEAT_WINDOW_DAYS * 86400:
                repeat_customers += 1
                break

    delivery_days = sorted(
        o["delivery_days"] for o in orders if o.get("delivery_days") is not None
    )
    p50 = delivery_days[len(delivery_days) // 2] if delivery_days else None
    total_customers = len(by_customer)

    return {
        "repeat_rate": round(repeat_customers / total_customers, 4) if total_customers else None,
        "delivery_days_p50": p50,
        "order_volume": len(orders),
    }


def wish_category_stats(rows: list[dict]) -> dict[str, Any]:
    """Pure transform: Wish summer-products rows (each at least
    {"price": float|None, "units_sold": int|None, "rating": float|None,
    "rating_count": int|None}) -> {price_band, units_sold_median,
    rating_mean, review_volume}.

    This dataset has no per-product-category column (it's a single-niche
    "summer products" export) — the loader below buckets every row under
    one category key, "wish_summer_products", rather than pretending a
    finer taxonomy exists. units_sold_median is this source's genuinely
    new signal vs. Amazon/Olist: Wish's `units_sold` column is a real,
    directly-observed sales-velocity figure (Amazon Reviews 2023 and Olist
    both only offer proxies — review volume, repeat-purchase rate).
    """
    prices = sorted(r["price"] for r in rows if r.get("price") is not None and r["price"] > 0)
    units = sorted(r["units_sold"] for r in rows if r.get("units_sold") is not None)
    ratings = [r["rating"] for r in rows if r.get("rating") is not None]

    def _percentile(sorted_vals: list[float], p: float) -> float | None:
        if not sorted_vals:
            return None
        idx = min(len(sorted_vals) - 1, max(0, round(p * (len(sorted_vals) - 1))))
        return round(sorted_vals[idx], 2)

    return {
        "price_band": {
            "p25": _percentile(prices, 0.25),
            "p50": _percentile(prices, 0.50),
            "p75": _percentile(prices, 0.75),
        },
        "units_sold_median": _percentile(units, 0.50),
        "rating_mean": round(sum(ratings) / len(ratings), 3) if ratings else None,
        "review_volume": len(rows),
    }


def merge_priors(*sources: dict[str, dict]) -> dict[str, dict]:
    """Combine any number of per-category stats dicts (Amazon, Olist, Wish,
    ...) — later sources' fields win on key collision, earlier sources
    fill in fields a later one doesn't have. A category present in only
    one source still gets a partial entry: consumers (category_prior())
    already treat a missing field as "no prior" and fall back to their own
    default, so a partial entry degrades gracefully field-by-field rather
    than needing every source to have data for that category."""
    categories: set[str] = set()
    for source in sources:
        categories.update(source)
    merged: dict[str, dict] = {}
    for cat in categories:
        entry: dict[str, Any] = {}
        for source in sources:
            entry.update(source.get(cat, {}))
        merged[cat] = entry
    return merged


# ── loaders (real filesystem access — only exercised when this script is
# actually run against real downloaded data, never in tests) ────────────────

def _load_amazon_metadata(amazon_dir: str, hf_category: str) -> list[dict]:
    from datasets import load_from_disk
    ds = load_from_disk(os.path.join(amazon_dir, hf_category))
    return [{"price": row.get("price"), "average_rating": row.get("average_rating")}
            for row in ds]


def _load_olist_orders_by_category(olist_dir: str) -> dict[str, list[dict]]:
    import pandas as pd

    orders = pd.read_csv(
        os.path.join(olist_dir, "olist_orders_dataset.csv"),
        parse_dates=["order_purchase_timestamp", "order_delivered_customer_date"],
    )
    customers = pd.read_csv(os.path.join(olist_dir, "olist_customers_dataset.csv"))
    items = pd.read_csv(os.path.join(olist_dir, "olist_order_items_dataset.csv"))
    products = pd.read_csv(os.path.join(olist_dir, "olist_products_dataset.csv"))
    translation = pd.read_csv(
        os.path.join(olist_dir, "product_category_name_translation.csv"))

    merged = (
        orders.merge(customers, on="customer_id")
              .merge(items[["order_id", "product_id"]].drop_duplicates("order_id"), on="order_id")
              .merge(products[["product_id", "product_category_name"]], on="product_id")
              .merge(translation, on="product_category_name", how="left")
    )
    merged["delivery_days"] = (
        merged["order_delivered_customer_date"] - merged["order_purchase_timestamp"]
    ).dt.days
    merged["order_purchase_timestamp"] = (
        merged["order_purchase_timestamp"].astype("int64") // 10**9
    )
    category_col = merged["product_category_name_english"].fillna(
        merged["product_category_name"])

    by_category: dict[str, list[dict]] = {}
    for cat, group in merged.groupby(category_col):
        by_category[str(cat)] = group[
            ["customer_unique_id", "order_purchase_timestamp", "delivery_days"]
        ].to_dict("records")
    return by_category


def _load_wish_products(wish_csv_path: str) -> list[dict]:
    """Load the Wish summer-products CSV. Every row is returned under one
    bucket — see wish_category_stats()'s docstring for why this dataset
    has no real per-product category to split on."""
    import pandas as pd

    df = pd.read_csv(wish_csv_path)
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "price": row.get("price"),
            "units_sold": row.get("units_sold"),
            "rating": row.get("rating"),
            "rating_count": row.get("rating_count"),
        })
    return rows


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--amazon-dir", default="data/amazon_reviews_2023")
    parser.add_argument("--amazon-categories", default="",
                        help="comma-separated HF config names to ingest, "
                             "e.g. raw_meta_Pet_Supplies,raw_meta_Baby_Products")
    parser.add_argument("--olist-dir", default="data/olist")
    parser.add_argument("--skip-olist", action="store_true",
                        help="ingest Amazon categories only")
    parser.add_argument("--wish-csv", default="",
                        help="path to the downloaded Wish summer-products CSV "
                             "(omit to skip this source)")
    parser.add_argument("--out", default="backend/data/seed/category_priors.json")
    args = parser.parse_args()

    amazon_stats: dict[str, dict] = {}
    categories = [c.strip() for c in args.amazon_categories.split(",") if c.strip()]
    for hf_category in categories:
        try:
            rows = _load_amazon_metadata(args.amazon_dir, hf_category)
            amazon_stats[hf_category] = amazon_category_stats(rows)
            _log.info("amazon_category_ingested category=%s rows=%d", hf_category, len(rows))
        except Exception as exc:
            _log.error("amazon_category_ingest_failed category=%s error=%s", hf_category, exc)

    olist_stats: dict[str, dict] = {}
    if not args.skip_olist:
        try:
            by_category = _load_olist_orders_by_category(args.olist_dir)
            for cat, rows in by_category.items():
                olist_stats[cat] = olist_category_stats(rows)
            _log.info("olist_ingested categories=%d", len(olist_stats))
        except Exception as exc:
            _log.error("olist_ingest_failed error=%s", exc)

    wish_stats: dict[str, dict] = {}
    if args.wish_csv:
        try:
            rows = _load_wish_products(args.wish_csv)
            wish_stats["wish_summer_products"] = wish_category_stats(rows)
            _log.info("wish_ingested rows=%d", len(rows))
        except Exception as exc:
            _log.error("wish_ingest_failed error=%s", exc)

    merged = merge_priors(amazon_stats, olist_stats, wish_stats)
    if not merged:
        print("No priors ingested — nothing written. Check the errors logged above; "
             "the datasets must be downloaded locally first (see this script's docstring).")
        return 1

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(merged, f, indent=2, sort_keys=True)
    print(f"Wrote priors for {len(merged)} categories to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
