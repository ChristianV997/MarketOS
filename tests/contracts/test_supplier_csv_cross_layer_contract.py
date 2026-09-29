"""Cross-layer contract: browser supplier-CSV preview vs backend manual importer.

Both real implementations read the same documented CSV and boundary cases from
``tests/fixtures/supplier_csv_contract/contract.json``:

* backend: ``import_csv`` -> ``build_report`` (no parsing logic here);
* frontend: ``frontend/src/lib/supplierCsvParser.ts`` driven through
  ``supplier_csv_frontend_runner.mjs`` (a thin adapter, no parsing logic).

The contract is deliberately small: stable ``candidate_id`` identity, manual/
unverified provenance, missing-vs-explicit-zero costs, malformed identity and
costs. The backend importer is the authority; the preview may be stricter but
must not be more permissive or show different values for the same identity.

Lifecycle of a ``differences`` entry in the contract:

* ``intentional``: the layer's behaviour is pinned exactly and stays green.
* ``defect``: asserted as ``xfail(strict=True)``. When the named owner fixes it
  the test XPASSes and fails the run until the entry is removed, so a fixed
  defect cannot linger and a new one cannot hide.

The suite activates once both supplier CSV changes are in the tree (documented
sample declares ``candidate_id`` and the frontend parser exists); until then it
skips with an explicit reason instead of asserting against a half-integrated
tree. No network, credentials, uploads or mutations are involved.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "tests" / "fixtures" / "supplier_csv_contract" / "contract.json"
RUNNER = Path(__file__).with_name("supplier_csv_frontend_runner.mjs")
FRONTEND_PARSER = ROOT / "frontend" / "src" / "lib" / "supplierCsvParser.ts"

CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = CONTRACT["cases"]
PROJECTION = CONTRACT["projection"]
LAYERS = ("backend", "frontend")


def _documented_sample_declares_identity() -> bool:
    sample = next(case for case in CASES if case["id"] == "documented_sample")
    header = (ROOT / sample["csv_file"]).read_text(encoding="utf-8-sig").splitlines()[0]
    return "candidate_id" in header.split(",")


BACKEND_SKIP = None if _documented_sample_declares_identity() else (
    "documented supplier_catalog_sample.csv has no candidate_id column: backend CSV identity "
    "contract (PR #359) is not in this tree"
)
FRONTEND_SKIP = (
    "frontend supplierCsvParser.ts is not in this tree (PR #364 not integrated)"
    if not FRONTEND_PARSER.is_file()
    else ("node is not available" if shutil.which("node") is None else None)
)
BOTH_SKIP = BACKEND_SKIP or FRONTEND_SKIP


def _csv_text(case: dict[str, Any]) -> str:
    if "csv_file" in case:
        return (ROOT / case["csv_file"]).read_text(encoding="utf-8")
    return case["csv"]


def _token(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return PROJECTION["non_finite_token"]["nan"]
    if isinstance(value, float) and math.isinf(value):
        return PROJECTION["non_finite_token"]["inf"] if value > 0 else "-" + PROJECTION["non_finite_token"]["inf"]
    return value


def _backend_projection(case: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    from backend.adapters.research.supplier_feasibility import SupplierImportError, import_csv
    from evaluation.commerce.supplier_feasibility import build_report

    if "csv_file" in case:
        source = ROOT / case["csv_file"]
    else:
        source = tmp_path / f"{case['id']}.csv"
        source.write_bytes(case["csv"].encode("utf-8"))
    try:
        records = import_csv(source)
    except SupplierImportError:
        return {"file_rejected": True, "rows": [], "evidence_modes": [], "safety": None}
    report = build_report(records, evidence_mode="manual_import").to_dict()
    rows = []
    modes = set()
    for candidate in report["candidates"]:
        offer = candidate["offers"][0]
        modes.add(offer["evidence_mode"])
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "unit_cost": _token(offer["unit_cost"]),
                "shipping_cost": _token(offer["shipping_cost"]),
                "landed_cost": _token(offer["estimated_landed_cost"]),
                "moq": offer["moq"],
            }
        )
    rows.sort(key=lambda row: row["candidate_id"])
    safety = {key: report[key] for key in ("read_only", "network_calls", "mutated")}
    return {"file_rejected": False, "rows": rows, "evidence_modes": sorted(modes), "safety": safety}


def _frontend_projections() -> dict[str, dict[str, Any]]:
    payload = {
        "cases": [{"id": case["id"], "csv": _csv_text(case)} for case in CASES],
        "rejectsRow": PROJECTION["preview_rejects_row_issues"],
        "rejectsFile": PROJECTION["preview_rejects_file_issues"],
    }
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(RUNNER), str(ROOT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"frontend runner failed: {result.stderr.strip()[:500]}"
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def frontend_actual() -> dict[str, dict[str, Any]]:
    if FRONTEND_SKIP:
        pytest.skip(FRONTEND_SKIP)
    return _frontend_projections()


def _number_matches(field: str, actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        tolerance = PROJECTION["landed_cost_tolerance"] if field == "landed_cost" else 1e-9
        return abs(actual - expected) <= tolerance
    return actual == expected


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Compare only the fields the contract case asserts; null and 0 never conflate."""
    if actual["file_rejected"] is not expected.get("file_rejected", False):
        return False
    if len(actual["rows"]) != len(expected["rows"]):
        return False
    for got, want in zip(actual["rows"], expected["rows"]):
        for field, value in want.items():
            if not _number_matches(field, got.get(field), value):
                return False
    return True


def _params(layer: str) -> list[Any]:
    skip = BACKEND_SKIP if layer == "backend" else FRONTEND_SKIP
    params = []
    for case in CASES:
        marks = [pytest.mark.skipif(bool(skip), reason=skip or "")]
        difference = case.get("differences", {}).get(layer)
        if difference and difference["status"] == "defect":
            marks.append(
                pytest.mark.xfail(
                    strict=True,
                    reason=f"defect owned by {difference['owner']}: {difference['note']}",
                )
            )
        params.append(pytest.param(case, id=case["id"], marks=marks))
    return params


def _assert_layer(case: dict[str, Any], layer: str, actual: dict[str, Any]) -> None:
    difference = case.get("differences", {}).get(layer)
    if difference and difference["status"] == "intentional":
        assert _matches(actual, difference["actual"]), (
            f"{case['id']}: intentional {layer} difference drifted: {actual['rows']} != {difference['actual']['rows']}"
        )
        return
    assert _matches(actual, case["expected"]), (
        f"{case['id']}: {layer} {actual['file_rejected']=} {actual['rows']} != contract {case['expected']}"
    )


def test_contract_is_well_formed() -> None:
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    allowed_fields = set(PROJECTION["fields"])
    for case in CASES:
        assert ("csv" in case) != ("csv_file" in case), case["id"]
        if "csv_file" in case:
            assert (ROOT / case["csv_file"]).is_file(), case["id"]
        assert set(case["expected"]) <= {"rows", "file_rejected"}
        for row in case["expected"]["rows"]:
            assert row["candidate_id"], case["id"]
            assert set(row) <= allowed_fields, case["id"]
        for layer, difference in case.get("differences", {}).items():
            assert layer in LAYERS, case["id"]
            assert difference["status"] in CONTRACT["difference_status"], case["id"]
            assert difference["owner"] and difference["note"], case["id"]
            assert "actual" in difference, case["id"]


@pytest.mark.parametrize("case", _params("backend"))
def test_backend_importer_conforms(case: dict[str, Any], tmp_path: Path) -> None:
    _assert_layer(case, "backend", _backend_projection(case, tmp_path))


@pytest.mark.parametrize("case", _params("frontend"))
def test_frontend_preview_conforms(case: dict[str, Any], frontend_actual: dict[str, Any]) -> None:
    _assert_layer(case, "frontend", frontend_actual[case["id"]])


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(case, id=case["id"], marks=[pytest.mark.skipif(bool(BOTH_SKIP), reason=BOTH_SKIP or "")])
        for case in CASES
        if not case.get("differences")
    ],
)
def test_layers_agree_where_no_difference_is_declared(
    case: dict[str, Any], frontend_actual: dict[str, Any], tmp_path: Path
) -> None:
    backend = _backend_projection(case, tmp_path)
    frontend = frontend_actual[case["id"]]
    assert backend["file_rejected"] == frontend["file_rejected"]
    assert [row["candidate_id"] for row in backend["rows"]] == [row["candidate_id"] for row in frontend["rows"]]
    for field in PROJECTION["fields"]:
        for b_row, f_row in zip(backend["rows"], frontend["rows"]):
            if field == "moq" and "moq" not in case["expected"]["rows"][0]:
                continue  # the preview does not carry moq when the case does not assert it
            assert _number_matches(field, f_row.get(field), b_row.get(field)), (case["id"], field, b_row, f_row)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            case,
            id=case["id"],
            marks=[pytest.mark.skipif(bool(FRONTEND_SKIP), reason=FRONTEND_SKIP or "")]
            + (
                [pytest.mark.xfail(strict=True, reason="row absent while a frontend defect on this case is open")]
                if case.get("differences", {}).get("frontend", {}).get("status") == "defect"
                else []
            ),
        )
        for case in CASES
        if "preview" in case
    ],
)
def test_preview_advisory_strictness(case: dict[str, Any], frontend_actual: dict[str, Any]) -> None:
    row = frontend_actual[case["id"]]["rows"][0]["preview"]
    assert row["valid"] is case["preview"]["valid"]
    assert set(case["preview"].get("issues", [])) <= set(row["issues"])


@pytest.mark.skipif(bool(BACKEND_SKIP), reason=BACKEND_SKIP or "")
def test_backend_never_upgrades_manual_evidence_or_gains_authority(tmp_path: Path) -> None:
    for case in CASES:
        projection = _backend_projection(case, tmp_path)
        assert set(projection["evidence_modes"]) <= {"manual_import"}, case["id"]
        if projection["safety"] is not None:
            assert projection["safety"] == {"read_only": True, "network_calls": False, "mutated": False}, case["id"]


@pytest.mark.skipif(bool(FRONTEND_SKIP), reason=FRONTEND_SKIP or "")
def test_frontend_labels_every_case_manual_evidence(frontend_actual: dict[str, Any]) -> None:
    assert {result["evidence_mode"] for result in frontend_actual.values()} == {"manual_import"}
