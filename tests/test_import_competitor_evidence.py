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


def test_ordinary_product_text_is_not_treated_as_contact():
    text = (
        "listing_id,title,seller,brand,availability,price,currency,shipping_cost\n"
        "a1,Copper Bottle 500ml 2 @ pack,ACME Supply,Northwind,in stock,10,USD,\n"
        "a2,Model 12-34-5678 UPC 012345678905,ACME Supply,Northwind,ships in 2 days,0,USD,0\n"
    )
    result = import_manual_competitor_csv(text, candidate_id="cand-1")
    assert result["status"] == "accepted"
    by_id = {offer["external_listing_id"]: offer for offer in result["offers"]}
    assert by_id["a1"]["title"] == "Copper Bottle 500ml 2 @ pack"
    assert by_id["a1"]["seller"] == "ACME Supply"
    assert by_id["a1"]["shipping_cost"] is None
    assert by_id["a2"]["price"] == 0.0
    assert by_id["a2"]["shipping_cost"] == 0.0
    assert by_id["a2"]["title"] == "Model 12-34-5678 UPC 012345678905"
    unknown = import_manual_competitor_csv(
        "listing_id,headphones,price\na1,Studio Pro,10\n",
        candidate_id="cand-1",
    )
    assert unknown["rejections"][0]["field"] == "headphones"
    assert "Studio Pro" not in json.dumps(unknown)


def test_contact_canaries_never_reach_records_warnings_or_errors():
    canaries = (
        "canary.ada@secret.test",
        "canary(at)secret.test",
        "canary[at]secret.test",
        "canary.ada @ secret.test",
        "(415) 555-0199",
        "+44 20 7946 0958",
        "415-555-0134",
        "mailto:canary.ada@secret.test",
        "tel:+1-415-555-0199",
        "https://cdn.example/p.png?e=canary.ada%40secret.test",
        "canary.ada" + "&" + "amp;#64;secret.test",
    )
    fields = ("listing_id", "title", "seller", "brand", "availability", "source", "source_url", "image")
    for field in fields:
        for canary in canaries:
            row = {
                "listing_id": "bad1",
                "title": "Copper Bottle",
                "seller": "ACME Supply",
                "brand": "Northwind",
                "availability": "in stock",
                "source": "manual",
                "source_url": "https://shop.example/copper",
                "image": "https://cdn.example/copper.png",
                "price": "10",
                "currency": "USD",
            }
            row[field] = canary
            columns = list(row)
            text = ",".join(columns) + "\n" + ",".join(row[column] for column in columns) + "\n"
            result = import_manual_competitor_csv(text, candidate_id="cand-1")
            blob = json.dumps(result)
            assert canary not in blob, (field, canary)
            assert "canary.ada" not in blob, (field, canary)
            assert result["offer_count"] == 0
    kept = (
        "listing_id,title,price,currency\n"
        "good1,Copper Bottle,10,USD\n"
        "bad1,leak canary.ada@secret.test,9,USD\n"
    )
    mixed = import_manual_competitor_csv(kept, candidate_id="cand-1")
    assert mixed["offer_count"] == 1
    assert mixed["offers"][0]["external_listing_id"] == "good1"
    assert "canary.ada@secret.test" not in json.dumps(mixed)
    header_cases = (
        "canary.ada@secret.test",
        "(415) 555-0199",
        "4155550199",
    )
    for header in header_cases:
        text = f"listing_id,title,{header},price,currency\na1,Copper Bottle,hidden-canary-cell,10,USD\n"
        result = import_manual_competitor_csv(text, candidate_id="cand-1")
        blob = json.dumps(result)
        assert header not in blob
        assert "hidden-canary-cell" not in blob
        assert result["status"] == "accepted"
        assert result["offers"][0]["title"] == "Copper Bottle"
    labeled = import_manual_competitor_csv(
        "listing_id,title,customer email,price,currency\na1,Copper Bottle,canary.ada@secret.test,10,USD\n",
        candidate_id="cand-1",
    )
    assert "canary.ada@secret.test" not in json.dumps(labeled)
    assert labeled["status"] == "accepted"
    assert labeled["offers"][0]["title"] == "Copper Bottle"
    phone_id = "415-555-0199"
    rejected_id = import_manual_competitor_csv("listing_id,price\na1,1\n", candidate_id=phone_id)
    assert phone_id not in json.dumps(rejected_id)
    assert rejected_id["candidate_id"] is None
    assert rejected_id["rejections"][0]["code"] == "invalid_candidate_id"
    email_id = import_manual_competitor_csv(
        "listing_id,price\na1,1\n",
        candidate_id="canary.ada@secret.test",
    )
    assert "canary.ada@secret.test" not in json.dumps(email_id)


def test_cli_exception_and_streams_do_not_echo_canaries(capsys, monkeypatch, tmp_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "import_competitor_evidence_cli",
        ROOT / "scripts" / "import_competitor_evidence.py",
    )
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    canary = "canary.ada@secret.test"

    def explode(*_args, **_kwargs):
        raise RuntimeError(f"boom {canary}")

    monkeypatch.setattr(cli, "import_manual_competitor_csv", explode)
    path = tmp_path / "offers.csv"
    path.write_text("listing_id,title,price,currency\na1,Copper Bottle,3,USD\n", encoding="utf-8")
    code = cli.main(["--csv", str(path), "--candidate-id", "cand-1"])
    captured = capsys.readouterr()
    assert code == 1
    assert canary not in captured.out
    assert canary not in captured.err
    assert "boom" not in captured.out
    assert "Traceback" not in captured.err
    leaked = tmp_path / "leaked.csv"
    leaked.write_text(
        "listing_id,title,price,currency\ngood1,Copper Bottle,4,USD\nbad1,canary.ada@secret.test,4,USD\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "scripts/import_competitor_evidence.py", "--csv", str(leaked), "--candidate-id", "cand-1"],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert canary not in completed.stdout
    assert canary not in completed.stderr
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["offer_count"] == 1
    blocked_id = subprocess.run(
        [sys.executable, "scripts/import_competitor_evidence.py", "--csv", str(path), "--candidate-id", canary],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert canary not in blocked_id.stdout
    assert canary not in blocked_id.stderr
    assert blocked_id.returncode == 1


def test_obfuscated_and_encoded_contact_is_not_returned():
    canaries = (
        "canary.ada [at] secret [dot] test",
        "canary.ada(at)secret(dot)test",
        "canary.ada AT secret DOT test",
        "canary.ada&#x40;secret.test",
        "canary.ada" + "\u200b" + "@secret.test",
        "canary.ada\uff20secret.test",
        "415\u2011555\u20110199",
        "(415)\u00a0555-0199",
        "\uff14\uff11\uff15-\uff15\uff15\uff15-\uff10\uff11\uff19\uff19",
        "+442079460958",
    )
    normalized = ("canary.ada@secret.test", "415-555-0199", "442079460958")
    fields = ("title", "seller", "brand", "availability")
    for field in fields:
        for canary in canaries:
            row = {
                "listing_id": "bad1",
                "title": "Copper Bottle",
                "seller": "ACME Supply",
                "brand": "Northwind",
                "availability": "in stock",
                "price": "10",
                "currency": "USD",
            }
            row[field] = canary
            columns = list(row)
            text = ",".join(columns) + "\n" + ",".join(row[column] for column in columns) + "\n"
            result = import_manual_competitor_csv(text, candidate_id="cand-1")
            blob = json.dumps(result)
            assert canary not in blob, (field, canary)
            for visible in normalized:
                assert visible not in blob, (field, canary, visible)
            assert result["offer_count"] == 0
    priced = import_manual_competitor_csv(
        "listing_id,title,price,currency\na1,Copper Bottle,+442079460958,USD\n",
        candidate_id="cand-1",
    )
    assert "442079460958" not in json.dumps(priced)
    assert priced["offer_count"] == 0
    preserved = import_manual_competitor_csv(
        "listing_id,title,price,shipping_cost,currency\n"
        "a1,gain +20 pack,,0,USD\n"
        "a2,Copper Bottle 500ml 2 @ pack,0,,USD\n",
        candidate_id="cand-1",
    )
    by_id = {offer["external_listing_id"]: offer for offer in preserved["offers"]}
    assert preserved["status"] == "accepted"
    assert by_id["a1"]["title"] == "gain +20 pack"
    assert by_id["a1"]["price"] is None
    assert by_id["a1"]["shipping_cost"] == 0.0
    assert by_id["a2"]["price"] == 0.0
    assert by_id["a2"]["shipping_cost"] is None
    header = "415\u2011555\u20110199"
    hidden = import_manual_competitor_csv(
        f"listing_id,title,{header},price,currency\na1,Copper Bottle,hidden-canary-cell,10,USD\n",
        candidate_id="cand-1",
    )
    hidden_blob = json.dumps(hidden)
    assert header not in hidden_blob
    assert "415-555-0199" not in hidden_blob
    assert "hidden-canary-cell" not in hidden_blob
    assert hidden["status"] == "accepted"
    assert hidden["offers"][0]["title"] == "Copper Bottle"
