"""Documented operator entry point for services.market_research.

Builds the existing product-agnostic Market Research report from a bounded
local manifest of already-computed pillar reports (marketplace, supplier,
consumer-attention, public-market-benchmark, product-validation). This is
an offline orchestration seam only: it does not fetch, scrape, or call any
provider, and it does not add a second scoring, ranking, or fusion
authority -- it composes services.market_research.build_market_research_report
exactly as that module already exists.

Manifest shape (all fields optional except candidate_id):
{
  "candidate_id": "cand-1",
  "workspace_id": "workspace-1",
  "offering_kind": "goods",
  "geography": "MX",
  "language": "es",
  "as_of": "2026-09-23",
  "marketplace_report": {...} | "marketplace_report_path": "relative/path.json",
  "supplier_report": {...} | "supplier_report_path": "relative/path.json",
  "consumer_report": {...} | "consumer_report_path": "relative/path.json",
  "public_market_benchmark_report": {...} | "public_market_benchmark_report_path": "relative/path.json",
  "product_validation_report": {...} | "product_validation_report_path": "relative/path.json",
  "client_context": {...}
}

Each ``*_report`` field must already be the exact dict shape the
corresponding existing authority produces (see
services/market_research/schemas.py's MarketResearchRequest docstring). An
omitted pillar is reported as missing by build_market_research_report, not
guessed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.market_research import MarketResearchRequest, build_market_research_report, render_market_research_markdown

_REPORT_FIELDS = (
    "marketplace_report",
    "supplier_report",
    "consumer_report",
    "public_market_benchmark_report",
    "product_validation_report",
)


class MarketResearchOperatorError(ValueError):
    """Stable failure for a malformed or unsafe manifest."""


def load_manifest(path: str) -> tuple[dict[str, Any], Path]:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise MarketResearchOperatorError(f"manifest not found: {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MarketResearchOperatorError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise MarketResearchOperatorError("manifest must be a JSON object")
    return manifest, manifest_path.parent


def _resolve_report(manifest: dict[str, Any], base_dir: Path, field: str) -> dict[str, Any] | None:
    if field in manifest and manifest[field] is not None:
        value = manifest[field]
        if not isinstance(value, dict):
            raise MarketResearchOperatorError(f"{field} must be a JSON object")
        return value
    path_key = f"{field}_path"
    if path_key in manifest and manifest[path_key]:
        report_path = (base_dir / str(manifest[path_key])).resolve()
        if base_dir.resolve() not in report_path.parents and report_path != base_dir.resolve():
            raise MarketResearchOperatorError(f"{path_key} must stay under the manifest's directory")
        if not report_path.is_file():
            raise MarketResearchOperatorError(f"{path_key} not found: {manifest[path_key]}")
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MarketResearchOperatorError(f"{path_key} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise MarketResearchOperatorError(f"{path_key} must contain a JSON object")
        return data
    return None


def build_request_from_manifest(manifest: dict[str, Any], base_dir: Path) -> MarketResearchRequest:
    candidate_id = manifest.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise MarketResearchOperatorError("manifest requires a non-empty candidate_id")
    client_context = manifest.get("client_context")
    if client_context is not None and not isinstance(client_context, dict):
        raise MarketResearchOperatorError("client_context must be a JSON object")
    kwargs: dict[str, Any] = {
        "candidate_id": candidate_id,
        "offering_kind": str(manifest.get("offering_kind", "unknown")),
        "geography": str(manifest.get("geography", "")),
        "language": str(manifest.get("language", "")),
        "as_of": str(manifest.get("as_of", "")),
        "workspace_id": str(manifest.get("workspace_id", "")),
        "client_context": client_context,
    }
    for field in _REPORT_FIELDS:
        kwargs[field] = _resolve_report(manifest, base_dir, field)
    return MarketResearchRequest(**kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True, help="path to a market-research manifest JSON file")
    parser.add_argument("--markdown", action="store_true", help="emit the consulting-ready Markdown report instead of JSON")
    parser.add_argument("--output", help="optional output file; no file is written by default")
    args = parser.parse_args(argv)

    try:
        manifest, base_dir = load_manifest(args.manifest)
        request = build_request_from_manifest(manifest, base_dir)
        result = build_market_research_report(request)
    except (OSError, MarketResearchOperatorError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, sort_keys=True))
        return 2

    payload = render_market_research_markdown(result) if args.markdown else json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
