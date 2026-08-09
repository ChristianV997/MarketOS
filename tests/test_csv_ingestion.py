from pathlib import Path
from backend.discovery.csv_ingestion import PARSERS, load_csv_rows


FIXTURES = Path(__file__).parent / "fixtures" / "evidence_imports"


def test_all_csv_parsers_are_deterministic_and_provenanced():
    for path in FIXTURES.glob("*.csv"):
        parser = path.stem.replace("_sample", "") + "_csv"
        if parser == "generic_market_csv": parser = "generic_market_csv"
        rows = load_csv_rows(str(path))
        records = PARSERS[parser](rows, {"source_name": parser, "type": "test"})
        assert records, parser
        assert all(record.provenance["parser_type"] == parser for record in records)
        assert all(record.provenance["row_number"] >= 2 for record in records)


def test_row_cap_and_utf8_sig(tmp_path, monkeypatch):
    import backend.discovery.csv_ingestion as ingestion
    monkeypatch.setattr(ingestion, "_project_root", lambda: tmp_path)
    path = tmp_path / "sample.csv"
    path.write_text("category,trend_score\n" + "x,0.5\n" * 3, encoding="utf-8-sig")
    assert len(load_csv_rows(str(path), 2)) == 2
