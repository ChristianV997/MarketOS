"""Offline CLI for manual competitor offer evidence intake."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.adapters.research.competition_evidence import import_csv

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB limit
MAX_ROWS = 1000

def _get_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0

def _sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Sanitize internal representations, remove raw object refs."""
    return {k: v for k, v in data.items() if not k.startswith("_")}

def main() -> int:
    parser = argparse.ArgumentParser(description="Import competitor offer evidence from a CSV.")
    parser.add_argument("--csv", type=Path, required=True, help="Path to the manual CSV file.")
    parser.add_argument("--candidate-id", type=str, required=True, help="Stable candidate identity to bind these offers to. Must not be inferred from text.")
    args = parser.parse_args()

    if not args.csv.exists() or not args.csv.is_file():
        print(f"Error: file not found or is not a file: {args.csv}", file=sys.stderr)
        return 1

    file_size = _get_file_size(args.csv)
    if file_size > MAX_FILE_BYTES:
        print(f"Error: file exceeds max size of {MAX_FILE_BYTES} bytes ({file_size} bytes).", file=sys.stderr)
        return 1

    if not args.candidate_id.strip():
        print("Error: --candidate-id cannot be empty.", file=sys.stderr)
        return 1

    try:
        offers = import_csv(args.csv)
    except Exception as exc:
        print(f"Error importing CSV: {exc}", file=sys.stderr)
        return 1

    if len(offers) > MAX_ROWS:
        print(f"Error: CSV exceeds max row count of {MAX_ROWS} ({len(offers)} rows found).", file=sys.stderr)
        return 1

    # Format the result with candidate_id boundary
    results = []
    for offer in offers:
        sanitized_offer = {
            "candidate_id": args.candidate_id,
            "source": offer.source,
            "source_url": offer.source_url,
            "external_listing_id": offer.external_listing_id,
            "title": offer.title,
            "price": offer.price,
            "shipping_cost": offer.shipping_cost,
            "currency": offer.currency,
            "availability": offer.availability,
            "brand": offer.brand,
            "seller": offer.seller,
            "rating": offer.rating,
            "review_count": offer.review_count,
            "extraction_method": offer.extraction_method,
            "confidence": offer.confidence,
            "field_status": offer.field_status,
            "warnings": offer.warnings,
        }
        results.append(sanitized_offer)

    payload = {
        "candidate_id": args.candidate_id,
        "evidence_mode": "manual",
        "imported_offers": results,
        "offer_count": len(results)
    }

    # Print deterministic JSON to stdout
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
