"""Run a bounded, read-only Phase 1 public-market evidence benchmark."""
from __future__ import annotations

import argparse
import errno
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.public_market_benchmark import (
    build_public_market_benchmark,
    load_public_market_seed,
    markdown_report,
    synthesize_from_public_market,
    to_marketplace_trend_report,
)

DEFAULT_SEED = ROOT / "tests" / "fixtures" / "public_market_benchmark" / "candidates.json"
ARTIFACTS = (ROOT / "artifacts").resolve()


OUTPUT_ERROR = "--output must resolve to a path under the repository artifacts/ directory"


class OutputConfinementError(Exception):
    """The output location is, or at write time became, outside artifacts/."""


def _within_artifacts(path: Path, *, allow_root: bool) -> bool:
    return ARTIFACTS in path.parents or (allow_root and path == ARTIFACTS)


def _confined_output(value: str) -> Path | None:
    """Resolve ``--output`` (following symlinks) and accept it only strictly under ``artifacts/``."""
    try:
        path = Path(value).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return path if _within_artifacts(path, allow_root=False) else None


def _resolved_directory(directory: Path) -> Path:
    try:
        resolved = directory.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise OutputConfinementError from exc
    if not _within_artifacts(resolved, allow_root=True):
        raise OutputConfinementError
    return resolved


def _make_dir(directory: Path) -> None:
    """Create ``directory`` only after resolving it again and confirming it is still within artifacts/."""
    _resolved_directory(directory).mkdir(parents=True, exist_ok=True)


def _write_text(target: Path, text: str) -> None:
    """Write one file after re-checking confinement.

    The check in ``main`` can be minutes old (a live run fetches in between), so the parent is resolved again
    here and the leaf is opened without following symlinks where the platform supports it. This narrows the
    race to the interval between that resolve and the open; it does not close it.
    """
    parent = _resolved_directory(target.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(parent / target.name, flags, 0o666)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):  # symlink leaf (EMLINK: BSD); EISDIR, ENOSPC, ... are not confinement
            raise OutputConfinementError from exc
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def _dump(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _enrich(report: dict[str, object]) -> dict[str, object]:
    marketplace = to_marketplace_trend_report(report).to_dict()
    synthesis = synthesize_from_public_market(report).to_dict()
    enriched = dict(report)
    enriched["marketplace_trend_report"] = marketplace
    enriched["opportunity_synthesis"] = synthesis
    return enriched


def _write(output: str, report: dict[str, object], rendered: str) -> None:
    path = Path(output)
    if path.suffix:
        _make_dir(path.parent)
        _write_text(path, _dump(report))
        return
    _make_dir(path)
    _write_text(path / "public_market_benchmark_report.json", _dump(report))
    _write_text(path / "public_market_benchmark_report.md", rendered)
    _write_text(path / "benchmark_matrix_report.json", _dump(report["benchmark_matrix"]))
    _write_text(path / "marketplace_trend_report.json", _dump(report["marketplace_trend_report"]))
    _write_text(path / "opportunity_synthesis_report.json", _dump(report["opportunity_synthesis"]))
    readiness = {
        "public_market_benchmark_status": report["evidence_mode"],
        "candidates_tested": report["candidates_tested"],
        "competitor_pages_attempted": report["competitor_pages_attempted"],
        "competitor_offers_observed": report["competitor_offers_observed"],
        "pricing_coverage": report["pricing_coverage"],
        "top_candidate_from_public_market": report["top_candidate_from_public_market"],
        "remaining_supplier_blocker": report["remaining_supplier_blocker"],
        "next_best_action": report["next_best_action"],
        "marketplace_top_candidate_id": (report.get("marketplace_trend_report") or {}).get("top_candidate_id"),
        "opportunity_synthesis_recommendation": (report.get("opportunity_synthesis") or {}).get("overall_recommendation"),
    }
    _write_text(path / "readiness_summary.json", _dump(readiness))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-seed", default=str(DEFAULT_SEED))
    parser.add_argument("--allow-network", action="store_true", help="Explicitly permit bounded public GETs.")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--max-competitors-per-candidate", type=int, default=3)
    parser.add_argument("--output", help="Optional sanitized output directory under artifacts/.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    output = None
    if args.output:
        output = _confined_output(args.output)
        if output is None:
            parser.error(OUTPUT_ERROR)
    candidates, warnings = load_public_market_seed(args.candidate_seed)
    report = build_public_market_benchmark(
        candidates,
        allow_network=args.allow_network,
        max_candidates=args.max_candidates,
        max_competitors_per_candidate=args.max_competitors_per_candidate,
    ).to_dict()
    report["warnings"] = sorted(set([*report["warnings"], *warnings]))
    report = _enrich(report)
    rendered = markdown_report(report)
    if output is not None:
        try:
            _write(str(output), report, rendered)
        except OutputConfinementError:
            parser.error(f"{OUTPUT_ERROR} (detected at write time; files already written in this run may be incomplete)")
    print(rendered if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
