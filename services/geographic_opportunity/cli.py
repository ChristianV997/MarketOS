"""services.geographic_opportunity.cli -- deterministic, offline
operator entry point for ``services.geographic_opportunity``.

Reads one already-saved, operator-authored offer JSON file from local
disk, builds a ``GeographicOpportunityReport`` via
``report.build_geographic_opportunity_report``, and prints deterministic
JSON or Markdown to stdout (or an explicitly named output file).
Performs no network I/O, contacts no live provider (UN Comtrade
included), and writes nothing but the one explicitly-requested output
file -- it never mutates its input.

Usage::

    python -m services.geographic_opportunity.cli OFFER.json \\
        --generated-at 2026-02-10T00:00:00Z [--format json|markdown] \\
        [--output OUT_PATH]

``--generated-at`` is required rather than defaulting to the system
clock: this keeps a given invocation's output reproducible from its
inputs alone, matching ``report.py``'s own explicit ``generated_at``
parameter and ``TestDeterminism``'s expectations in
``tests/services/test_geographic_opportunity/test_report.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.economics.kernel import Money

from .report import build_geographic_opportunity_report
from .schemas import GeographicOpportunityReport
from .serialization import offer_from_dict

_FORMATS = ("json", "markdown")


def load_offer_file(path: Path) -> dict[str, Any]:
    """Reads and JSON-parses one local offer file. Performs no network
    access and no normalization beyond UTF-8 decoding; any parse error
    propagates to the caller unchanged."""
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _fmt_money(money: Money | None) -> str:
    if money is None:
        return "unknown"
    return f"{money.amount} {money.currency}"


def render_markdown(report: GeographicOpportunityReport) -> str:
    """A deterministic Markdown rendering of one report. Section order
    is fixed; ``evidence_quality_summary`` is emitted in sorted-key
    order since ``dict`` iteration order is otherwise an implementation
    detail this module should not depend on for reproducibility."""
    offer = report.offer
    lines: list[str] = [
        f"# Geographic Opportunity Report: {report.candidate_id}",
        "",
        f"- schema: `{report.schema}`",
        f"- generated_at: {report.generated_at}",
        f"- fingerprint: {report.fingerprint}",
        f"- status: {report.status}",
        f"- offering_kind: {offer.offering_kind}",
        f"- geography_kind: {offer.geography_kind}",
        f"- origin: {offer.identity.origin_country or 'unknown'}",
        f"- destination: {offer.identity.destination_country or 'unknown'}",
        f"- read_only: {report.read_only} / network_calls: {report.network_calls} / mutated: {report.mutated}",
        "",
        "## Blockers",
    ]
    if report.blockers:
        lines.extend(f"- {item}" for item in report.blockers)
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("## Evidence gaps")
    if report.evidence_gaps:
        lines.extend(f"- {item}" for item in report.evidence_gaps)
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("## Risk matrix")
    if report.risk_matrix:
        lines.append("| category | severity | evidence quality |")
        lines.append("|---|---|---|")
        for entry in report.risk_matrix:
            lines.append(f"| {entry.category} | {entry.severity} | {entry.evidence.quality} |")
    else:
        lines.append("- (empty -- see blockers above)")

    lines.append("")
    lines.append("## Landed-cost scenarios")
    if report.landed_cost_scenarios:
        lines.append("| scenario | net_sales | contribution_before_cac | missing_inputs |")
        lines.append("|---|---|---|---|")
        for scenario in report.landed_cost_scenarios:
            result = scenario.result
            missing = ", ".join(result.missing_inputs) or "(none)"
            lines.append(
                f"| {scenario.scenario_id} | {_fmt_money(result.net_sales)} | "
                f"{_fmt_money(result.contribution_before_cac)} | {missing} |"
            )
    else:
        lines.append("- (none -- see blockers above)")

    lines.append("")
    lines.append("## Destination/source comparison")
    if report.comparison is not None:
        comparison = report.comparison
        lines.append(f"- price_gap: {_fmt_money(comparison.price_gap)}")
        lines.append(f"- unit_value_proxy: {_fmt_money(comparison.unit_value_proxy)}")
        lines.append(f"- unit_value_conflicts_with_supplier_cost: {comparison.unit_value_conflicts_with_supplier_cost}")
        for note in comparison.notes:
            lines.append(f"  - note: {note}")
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("## Next actions")
    if report.next_actions:
        for action in report.next_actions:
            marker = "BLOCKING" if action.blocking else "non-blocking"
            lines.append(f"- [{marker}] {action.description}")
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("## Evidence quality summary")
    for quality in sorted(report.evidence_quality_summary):
        lines.append(f"- {quality}: {report.evidence_quality_summary[quality]}")
    lines.append("")

    return "\n".join(lines)


def render(report: GeographicOpportunityReport, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if fmt == "markdown":
        return render_markdown(report)
    raise ValueError(f"unsupported format: {fmt!r}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.geographic_opportunity.cli",
        description=(
            "Deterministic, offline operator entry point for "
            "services.geographic_opportunity. Reads one operator-authored "
            "offer JSON file from local disk and prints a "
            "GeographicOpportunityReport as JSON or Markdown. Performs no "
            "network I/O and contacts no live provider."
        ),
    )
    parser.add_argument(
        "offer_path", type=Path, help="Path to a local offer JSON file (see serialization.offer_from_dict)."
    )
    parser.add_argument(
        "--generated-at",
        required=True,
        help="Explicit report timestamp, e.g. 2026-02-10T00:00:00Z. Never defaults to the system clock.",
    )
    parser.add_argument("--format", choices=_FORMATS, default="json", help="Output format (default: json).")
    parser.add_argument("--output", type=Path, default=None, help="Write output to this file instead of stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    offer_data = load_offer_file(args.offer_path)
    offer = offer_from_dict(offer_data)
    report = build_geographic_opportunity_report(offer, generated_at=args.generated_at)
    text = render(report, args.format)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
