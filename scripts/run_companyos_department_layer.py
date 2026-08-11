"""Generate the offline CompanyOS Department Layer operating review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.companyos.department_layer import build_companyos_report

SECRET_KEYS = {"password", "secret", "token", "api_key", "apikey", "private_key", "access_token", "refresh_token", "client_secret"}


def _safe_path(value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    if any(part == ".." for part in raw.parts):
        raise ValueError("path traversal is not accepted")
    path = raw if raw.is_absolute() else ROOT / raw
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _contains_secret(value: Any, path: str = "") -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SECRET_KEYS:
                return True
            if _contains_secret(item, f"{path}.{key}"):
                return True
    if isinstance(value, list):
        return any(_contains_secret(item, path) for item in value)
    return False


def _json_input(path_value: str | None) -> dict[str, Any] | None:
    path = _safe_path(path_value)
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    if _contains_secret(payload):
        raise ValueError(f"secret-like fields are not accepted in {path.name}")
    return payload


def _write_exports(directory: str, report: Any) -> None:
    output = Path(directory)
    if any(part == ".." for part in output.parts):
        raise ValueError("output traversal is not accepted")
    if not output.is_absolute():
        output = ROOT / output
    output.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    files = {
        "companyos_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "companyos_report.md": report.to_markdown(),
        "department_registry.json": json.dumps({"departments": data["departments"]}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "management_operating_review.md": "## Management Operating Review\n\n" + report.management.weekly_operating_review.ceo_summary + "\n",
        "finance_plan.json": json.dumps(data["finance"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "accounting_ledger_seed.json": json.dumps(data["accounting"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "sales_pipeline_seed.json": json.dumps(data["sales"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "service_catalog.json": json.dumps(data["service_catalog"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "approval_queue.json": json.dumps(data["approval_queue"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "risk_register.json": json.dumps(data["risk_register"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-context")
    parser.add_argument("--finance-context")
    parser.add_argument("--sales-context")
    parser.add_argument("--accounting-transactions")
    parser.add_argument("--service-catalog", action="store_true")
    parser.add_argument("--service-catalog-seed")
    parser.add_argument("--opportunity-synthesis-report")
    parser.add_argument("--launch-draft-pack")
    parser.add_argument("--site-draft-pack")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        company = _json_input(args.company_context) or {}
        finance = _json_input(args.finance_context)
        sales = _json_input(args.sales_context)
        catalog_seed = _json_input(args.service_catalog_seed) if args.service_catalog_seed else None
        csv_path = _safe_path(args.accounting_transactions)
        source_reports: dict[str, str] = {}
        for key, value in (("opportunity_synthesis", args.opportunity_synthesis_report), ("launch_draft_pack", args.launch_draft_pack), ("site_draft_pack", args.site_draft_pack)):
            if value:
                _safe_path(value)
                source_reports[key] = "available"
        report = build_companyos_report(company_context=company, finance_context=finance, sales_context=sales, service_catalog_seed=catalog_seed, source_reports=source_reports, accounting_csv=csv_path.read_text(encoding="utf-8") if csv_path else None)
        if args.output:
            _write_exports(args.output, report)
        if args.markdown:
            print(report.to_markdown(), end="")
        else:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"companyos_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
