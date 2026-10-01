"""Offline competitor CSV intake. No live fetch."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

from backend.adapters.research.competition_evidence import MAX_RESPONSE_BYTES, import_manual_competitor_csv
from backend.discovery.csv_ingestion import MAX_ROWS

ROOT = Path(__file__).resolve().parents[1]


def test_candidate_id_is_required_and_not_inferred_from_title():
    missing = import_manual_competitor_csv("listing_id,title,price\na1,Copper Bottle,10\n", candidate_id="")
    assert missing["status"] == "rejected"
    assert missing["rejections"][0]["code"] == "invalid_candidate_id"
    assert "Copper Bottle" not in json.dumps(missing)
    unnamed = import_manual_competitor_csv("title,price,currency\nCopper Bottle,10,USD\n", candidate_id="cand-1")
    assert unnamed["status"] == "rejected"
    assert unnamed["rejections"][0]["code"] == "malformed_identity"
    assert "Copper Bottle" not in json.dumps(unnamed)
    named = import_manual_competitor_csv(
        "listing_id,title,price,currency\na1,Copper Bottle,10,USD\n",
        candidate_id="cand-1",
    )
    assert named["candidate_id"] == "cand-1"
    assert named["offers"][0]["external_listing_id"] == "a1"
    assert named["offers"][0]["title"] == "Copper Bottle"


def test_missing_amount_is_not_zero_and_replay_is_deterministic():
    text = "listing_id,price,currency,shipping_cost\na1,10.00,USD,\na2,0.00,EUR,0\n"
    first = import_manual_competitor_csv(text, candidate_id="cand-1")
    second = import_manual_competitor_csv(text, candidate_id="cand-1")
    assert first == second
    assert first["evidence_class"] == "manual"
    assert first["evidence_state"] == "manual_import"
    assert first["live_validated"] is False
    assert first["network_calls"] is False
    by_id = {offer["external_listing_id"]: offer for offer in first["offers"]}
    assert by_id["a1"]["price"] == 10.0
    assert by_id["a1"]["shipping_cost"] is None
    assert by_id["a1"]["field_status"]["shipping_cost"] == "missing"
    assert by_id["a1"]["currency"] == "USD"
    assert by_id["a2"]["price"] == 0.0
    assert by_id["a2"]["shipping_cost"] == 0.0
    assert by_id["a2"]["currency"] == "EUR"
    assert by_id["a2"]["crawl_timestamp"] == 0.0
    assert by_id["a2"]["extraction_method"] == "manual_csv"


def test_duplicates_collapse_conflicts_and_pii_do_not_leak():
    duplicate = "listing_id,price,currency,email\na1,5.00,USD,ada@example.test\na1,5.00,USD,ada@example.test\n"
    collapsed = import_manual_competitor_csv(duplicate, candidate_id="cand-1")
    assert collapsed["offer_count"] == 1
    assert "ada@example.test" not in json.dumps(collapsed)
    assert any(item.startswith("pii_columns_dropped:") for item in collapsed["warnings"])
    conflict = "listing_id,price,currency\na1,5.00,USD\na1,9.00,USD\n"
    rejected = import_manual_competitor_csv(conflict, candidate_id="cand-1")
    assert rejected["status"] == "rejected"
    assert rejected["rejections"][0]["code"] == "conflicting_listing"
    assert "9.00" not in json.dumps(rejected)


def test_bounds_and_cli_do_not_touch_the_network(monkeypatch, tmp_path: Path):
    def explode(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket, "getaddrinfo", explode)
    huge = "listing_id,price\n" + "".join(f"a{index},1\n" for index in range(MAX_ROWS + 1))
    assert import_manual_competitor_csv(huge, candidate_id="cand-1", max_rows=MAX_ROWS)["rejections"][0]["code"] == "row_limit_exceeded"
    path = tmp_path / "offers.csv"
    path.write_text("listing_id,price,currency\na1,3.50,USD\n", encoding="utf-8")
    oversized = tmp_path / "big.csv"
    oversized.write_bytes(b"x" * (MAX_RESPONSE_BYTES + 1))
    completed = subprocess.run(
        [sys.executable, "scripts/import_competitor_evidence.py", "--csv", str(path), "--candidate-id", "cand-1"],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "accepted"
    assert payload["offers"][0]["price"] == 3.5
    blocked = subprocess.run(
        [sys.executable, "scripts/import_competitor_evidence.py", "--csv", str(oversized), "--candidate-id", "cand-1"],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["rejections"][0]["code"] == "file_too_large"
    assert "x" * 20 not in blocked.stdout
