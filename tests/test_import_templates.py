import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.discovery.import_templates as tpl
from backend.discovery.csv_ingestion import PARSERS, load_csv_rows
from backend.discovery.import_recommendation import _FIELDS
from backend.discovery.import_templates import (
    TemplateCollisionError,
    TemplateError,
    create_import_template,
    create_templates_for_plan,
    kit_fields,
)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    # Every write lands in a temporary working directory, never in the shared checkout.
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_template_is_placeholder_and_safe(workdir):
    item = create_import_template("supplier_catalog_csv")
    assert item.file_path.endswith("supplier_catalog_csv.csv")
    assert item.example_rows[0]["category"] == "PLACEHOLDER_CATEGORY"
    assert item.metadata["not_real_market_data"] is True
    assert item.metadata["market_evidence"] is False


def test_template_path_traversal_rejected(workdir):
    with pytest.raises(ValueError):
        create_import_template("generic_market_csv", "data/import_templates/../outside")
    with pytest.raises(TemplateError, match="template_output_path_blocked"):
        create_import_template("generic_market_csv", str(workdir / "elsewhere"))


def test_field_contract_matches_the_importer_parsers():
    assert set(_FIELDS) == set(PARSERS)


@pytest.mark.parametrize("parser", sorted(_FIELDS))
def test_every_parser_contract_generates_header_manifest_and_placeholder_record(workdir, parser):
    required, optional = kit_fields(parser)
    item = create_import_template(parser)
    header = Path(item.file_path).read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    assert header == required + optional
    manifest = json.loads(Path(item.file_path).with_name(f"{parser}.manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_dictionary"] == [{"field": name, "required": name in required} for name in required + optional]
    assert manifest["provenance"]["market_evidence"] is False
    assert manifest["provenance"]["not_real_market_data"] is True
    assert manifest["round_trip"] == {"verified": True, "parser_records": item.metadata["round_trip_records"]}
    assert item.metadata["round_trip_records"] >= 1


@pytest.mark.parametrize("parser", sorted(_FIELDS))
def test_generation_is_byte_identical_across_runs(tmp_path, monkeypatch, parser):
    outputs = []
    for name in ("first", "second"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        monkeypatch.chdir(run_dir)
        item = create_import_template(parser)
        outputs.append((Path(item.file_path).read_bytes(), Path(item.file_path).with_name(f"{parser}.manifest.json").read_bytes()))
    assert outputs[0] == outputs[1]


def test_placeholder_records_are_marked_as_non_evidence(workdir):
    item = create_import_template("google_trends_csv")
    records = PARSERS["google_trends_csv"](load_csv_rows(item.file_path), {"source_name": "google_trends_csv", "type": "template"})
    assert records
    assert all(record.entity_name.startswith("PLACEHOLDER") for record in records)
    assert item.metadata["placeholder_only"] is True and item.metadata["market_evidence"] is False


def test_existing_operator_file_is_preserved_by_default(workdir):
    path = Path(create_import_template("google_trends_csv").file_path)
    path.write_text("OPERATOR OWNED\n", encoding="utf-8")
    with pytest.raises(TemplateCollisionError):
        create_import_template("google_trends_csv")
    assert path.read_text(encoding="utf-8") == "OPERATOR OWNED\n"


def test_identical_existing_template_is_left_unchanged(workdir):
    create_import_template("google_trends_csv")
    again = create_import_template("google_trends_csv")
    assert again.metadata["publish"] == "unchanged"


def test_overwrite_requires_an_explicit_opt_in(workdir):
    path = Path(create_import_template("google_trends_csv").file_path)
    path.write_text("OPERATOR OWNED\n", encoding="utf-8")
    replaced = create_import_template("google_trends_csv", overwrite=True)
    assert replaced.metadata["publish"] == "written"
    assert "OPERATOR OWNED" not in path.read_text(encoding="utf-8-sig")


def test_plan_keeps_an_operator_file_and_reports_it(workdir):
    path = Path(create_import_template("google_trends_csv").file_path)
    path.write_text("OPERATOR OWNED\n", encoding="utf-8")
    plan = SimpleNamespace(recommendations=[SimpleNamespace(parser_type="google_trends_csv", source_name_suggestion="google_trends")])
    templates = create_templates_for_plan(plan)
    assert len(templates) == 1
    assert templates[0].metadata["publish"] == "preserved_existing_operator_file"
    assert path.read_text(encoding="utf-8") == "OPERATOR OWNED\n"


def test_symlink_at_the_target_is_refused_and_the_outside_file_is_untouched(workdir):
    out = workdir / "data" / "import_templates"
    out.mkdir(parents=True)
    outside = workdir / "outside.csv"
    outside.write_text("UNTOUCHED\n", encoding="utf-8")
    try:
        os.symlink(outside, out / "google_trends_csv.csv")
    except OSError:
        pytest.skip("symlink creation requires privilege on this host")
    with pytest.raises(TemplateError, match="template_target_is_symlink"):
        create_import_template("google_trends_csv")
    assert outside.read_text(encoding="utf-8") == "UNTOUCHED\n"


def test_symlinked_output_root_is_refused(workdir):
    (workdir / "data").mkdir()
    elsewhere = workdir / "elsewhere"
    elsewhere.mkdir()
    try:
        os.symlink(elsewhere, workdir / "data" / "import_templates", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires privilege on this host")
    with pytest.raises(TemplateError, match="template_output_path_blocked"):
        create_import_template("generic_market_csv")
    assert list(elsewhere.iterdir()) == []


def test_failed_round_trip_publishes_nothing(workdir, monkeypatch):
    contract = dict(_FIELDS)
    contract["google_trends_csv"] = (["bogus_required"], [])
    monkeypatch.setattr(tpl, "_FIELDS", contract)
    out = workdir / "data" / "import_templates"
    with pytest.raises(TemplateError, match="template_round_trip_failed"):
        create_import_template("google_trends_csv")
    assert list(out.iterdir()) == []
