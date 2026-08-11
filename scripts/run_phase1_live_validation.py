"""Phase 1 live-validation harness.

Runs the real chain — real public page(s) -> Supplier Evidence ->
Competition Intelligence -> Opportunity Scoring -> Product Research
Portfolio -> Commerce MVP economics -> canonical events -> API/dashboard
read views — against operator-supplied CJ/competitor URLs, and produces
one JSON (+ optional Markdown) validation_report artifact.

This is a thin orchestration wrapper: it calls the existing, already-tested
entrypoints only (gather_supplier_evidence, gather_market_intelligence,
compute_margin_intelligence, run_commerce_mvp_slice, build_research_*,
event_query_report) — it does not reimplement extraction, scoring, or
event emission. The one genuinely new piece is `_diagnose_reachability()`:
an independent DNS + bounded-HTTP-probe check per target hostname, run
*outside* the adapters' own robots-first fetch order, so a blocked run
reports the true underlying failure mode (dns_failure / proxy_block /
timeout / tls_error / connection_error) rather than only the adapters' own
higher-level "robots.txt could not be verified" classification (which is
correct and conservative on its own terms, but doesn't distinguish *why*
robots.txt was unreachable).

Advisory, read-only, no provider mutation, no credentials, no CAPTCHA
bypass. Generated artifacts are written under artifacts/ and are never
committed (this repository's established convention — nothing under
artifacts/ is ever git-tracked).
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.contracts.adapters import SidecarContext
from backend.events.query_service import event_query_report, load_events_from_jsonl
from backend.events.query_models import EventQuery
from backend.events.repository import JsonlEventRepository
from backend.mvp_commerce.competition_intelligence import compute_margin_intelligence, gather_market_intelligence
from backend.mvp_commerce.opportunity import build_opportunity_candidates_from_signals, select_candidate
from backend.mvp_commerce.opportunity_scoring import score_opportunity
from backend.mvp_commerce.product_research import build_research_candidates, build_research_portfolio, product_research_events
from backend.mvp_commerce.runner import _load_signals, run_commerce_mvp_slice
from backend.mvp_commerce.supplier_evidence import gather_authenticated_supplier_evidence, gather_supplier_evidence
from backend.adapters.research.cj_readonly_api import explain_cj_read_only_readiness

DEFAULT_FIXTURE = ROOT / "tests/fixtures/commerce_mvp/public_signals.json"
FAILURE_MODES = (
    "reachable", "dns_failure", "proxy_block", "timeout", "tls_error",
    "connection_error", "redirect_rejected", "robots_disallow", "unknown",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phase 1 intelligence chain against real public URLs and produce one validation report.")
    parser.add_argument("--supplier-url", help="one real CJ product page URL")
    parser.add_argument("--supplier-source", choices=("public_static", "public_js", "authenticated_readonly", "unavailable"), default="public_static")
    parser.add_argument("--allow-authenticated-supplier", action="store_true", help="allow the separately gated CJ catalog read path")
    parser.add_argument("--competitor-urls", help="comma-separated real competitor product/storefront page URLs (3-5 recommended)")
    parser.add_argument("--query", default="portable espresso maker")
    parser.add_argument("--signal-fixture", default=str(DEFAULT_FIXTURE), help="deterministic public-signal fixture driving candidate selection (evidence gathering is still attempted against the real URLs above)")
    parser.add_argument("--allow-network", action="store_true", help="perform real fetches; without this, every evidence attempt is dry-run/simulated")
    parser.add_argument("--workspace-id", default="phase1-live-validation")
    parser.add_argument("--out-dir", help="defaults to artifacts/phase1_live_validation/<timestamp>/")
    parser.add_argument("--timestamp", help="override the timestamp used for --out-dir and the report's own generated_at label (for reproducible test runs)")
    parser.add_argument("--markdown", action="store_true", help="also write validation_report.md alongside the JSON artifact")
    return parser


def _diagnose_reachability(hostname: str, *, allow_network: bool) -> dict[str, Any]:
    """Independent of the adapters' own robots-first fetch order: resolve
    DNS, then attempt one bounded HTTPS HEAD, classifying the exact
    exception type. Never raises."""
    if not allow_network:
        return {"hostname": hostname, "checked": False, "failure_mode": "not_attempted", "detail": "dry_run: --allow-network not set"}
    result: dict[str, Any] = {"hostname": hostname, "checked": True, "dns_resolved": None, "resolved_ip": None, "failure_mode": "unknown", "detail": ""}
    try:
        infos = socket.getaddrinfo(hostname, None)
        result["dns_resolved"] = True
        result["resolved_ip"] = infos[0][4][0]
    except socket.gaierror as exc:
        result["dns_resolved"] = False
        result["failure_mode"] = "dns_failure"
        result["detail"] = str(exc)
        return result
    import requests

    try:
        response = requests.head(f"https://{hostname}/", timeout=8, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            result["failure_mode"] = "redirect_rejected"
            result["detail"] = f"HEAD returned {response.status_code}"
        else:
            result["failure_mode"] = "reachable"
            result["detail"] = f"HEAD returned {response.status_code}"
        result["http_status"] = response.status_code
    except requests.exceptions.ProxyError as exc:
        result["failure_mode"] = "proxy_block"
        result["detail"] = str(exc)
    except requests.exceptions.SSLError as exc:
        result["failure_mode"] = "tls_error"
        result["detail"] = str(exc)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.Timeout):
        result["failure_mode"] = "timeout"
        result["detail"] = "connection or read timed out after 8s"
    except requests.exceptions.ConnectionError as exc:
        result["failure_mode"] = "connection_error"
        result["detail"] = str(exc)
    return result


def _hostname(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower()


def _field_status_summary(field_status: dict[str, str]) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {}
    for field, status in field_status.items():
        summary.setdefault(status, []).append(field)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    from datetime import datetime, timezone
    timestamp = args.timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "artifacts" / "phase1_live_validation" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.jsonl"

    competitor_urls = [url.strip() for url in (args.competitor_urls or "").split(",") if url.strip()]
    supplier_url = args.supplier_url

    # 1. Network diagnosis, independent of the adapters' own fetch order.
    target_urls = ([supplier_url] if supplier_url and args.supplier_source != "authenticated_readonly" else []) + competitor_urls
    hosts = sorted({_hostname(url) for url in target_urls if url})
    if args.supplier_source == "authenticated_readonly":
        hosts.append("developers.cjdropshipping.com")
    network_diagnosis = [_diagnose_reachability(host, allow_network=args.allow_network) for host in hosts]

    # 2. Candidate selection from a deterministic, already-reviewed fixture
    #    (evidence gathering below is still attempted against the real URLs).
    rows = _load_signals(Path(args.signal_fixture))
    candidates = build_opportunity_candidates_from_signals(rows, args.workspace_id, args.query, 5)
    selected = select_candidate(candidates)

    # 3. Real (or honestly-dry-run) supplier + competition evidence.
    context = SidecarContext(workspace_id=args.workspace_id, dry_run=not args.allow_network)
    supplier_evidence = None
    if selected is not None and args.supplier_source != "unavailable":
        if args.supplier_source == "authenticated_readonly":
            supplier_evidence = gather_authenticated_supplier_evidence(
                selected.product_name, context=context, max_candidates=5,
                allow_network=args.allow_network and args.allow_authenticated_supplier,
            )
        elif supplier_url:
            supplier_evidence = gather_supplier_evidence(selected.product_name, context=context, candidate_urls=[supplier_url])
    competition_evidence = None
    if competitor_urls and selected is not None:
        competition_evidence = gather_market_intelligence(selected.product_name, context=context, competitor_urls=competitor_urls)
    margin = compute_margin_intelligence(selected.candidate_id, supplier_evidence=supplier_evidence, market_report=competition_evidence) if selected is not None else None

    # 4. Full Commerce MVP run: opportunity scoring + economics + events.
    repository = JsonlEventRepository(events_path)
    run = run_commerce_mvp_slice(
        workspace_id=args.workspace_id, query=args.query, signals=rows, use_opportunity_ranking=True,
        supplier_evidence=supplier_evidence, competition_evidence=competition_evidence, write_repository=repository,
    )

    # 5. Product Research portfolio over the same scored candidates.
    scores = {selected.candidate_id: score_opportunity(selected, supplier_evidence=supplier_evidence, competition_evidence=competition_evidence, margin=margin)} if selected is not None else {}
    research_candidates = build_research_candidates(
        candidates, scores_by_id=scores,
        supplier_evidence_by_id={selected.candidate_id: supplier_evidence} if selected is not None and supplier_evidence is not None else {},
        competition_evidence_by_id={selected.candidate_id: competition_evidence} if selected is not None and competition_evidence is not None else {},
    )
    portfolio = build_research_portfolio(research_candidates, workspace_id=args.workspace_id, query=args.query, generated_at=run.started_at)
    research_events = product_research_events(portfolio, research_candidates, run_id=run.run_id)
    repository.append_many(research_events)

    # 6. Verify the API/dashboard read path over the real, on-disk JSONL.
    replayed_events, replay_warnings = load_events_from_jsonl(events_path)
    read_report = event_query_report(replayed_events, EventQuery(workspace_id=args.workspace_id, limit=500))

    # 7. Assemble the validation report.
    supplier_status = "unavailable" if args.supplier_source == "unavailable" else (
        "no_url_supplied" if args.supplier_source != "authenticated_readonly" and not supplier_url else
        ("observed" if supplier_evidence and supplier_evidence.unit_cost is not None else (supplier_evidence.status if supplier_evidence else "unavailable"))
    )
    competition_status = "no_urls_supplied" if not competitor_urls else ("observed" if competition_evidence and competition_evidence.observed_competitor_count > 0 else "unavailable")
    if not args.allow_network:
        overall_status = "degraded_dry_run"
        next_action = "Re-run with --allow-network from an environment with unrestricted egress (Railway or a local machine) to attempt real fetches."
    elif supplier_status == "observed" or competition_status == "observed":
        overall_status = "pass"
        next_action = "Review observed fields in the dashboard Competition & pricing / Opportunity ranking tabs; corroborate before any operator decision."
    elif any(diag["failure_mode"] not in ("reachable", "not_attempted") for diag in network_diagnosis):
        overall_status = "blocked"
        modes = sorted({diag["failure_mode"] for diag in network_diagnosis if diag["failure_mode"] not in ("reachable", "not_attempted")})
        next_action = f"Network egress blocked ({', '.join(modes)}) from this environment; re-run from Railway or a local machine with unrestricted egress."
    else:
        overall_status = "degraded"
        next_action = "Pages were reachable but exposed no usable structured product data; inspect the target URLs manually for schema.org Product JSON-LD."

    report: dict[str, Any] = {
        "generated_at": timestamp,
        "environment": {"sandboxed": True, "network_egress_policy": "outbound HTTPS proxy allowlist excludes general web domains"},
        "input_urls": {"supplier_url": supplier_url, "competitor_urls": competitor_urls, "query": args.query},
        "network_status": {"allow_network": args.allow_network, "diagnosis": network_diagnosis},
        "supplier_evidence": {
            "status": supplier_status,
            "source": args.supplier_source,
            "credential_readiness": explain_cj_read_only_readiness(allow_network=args.allow_network) if args.supplier_source == "authenticated_readonly" else None,
            "live_readonly_gate": bool(args.allow_authenticated_supplier and args.allow_network) if args.supplier_source == "authenticated_readonly" else False,
            "provider_status": supplier_evidence.status if supplier_evidence else None,
            "result": supplier_evidence.evidence.to_dict() if supplier_evidence and supplier_evidence.evidence else None,
            "field_status_summary": _field_status_summary(supplier_evidence.evidence.field_status) if supplier_evidence and supplier_evidence.evidence else None,
            "warnings": list(supplier_evidence.warnings) if supplier_evidence else [],
        },
        "competition_evidence": {
            "status": competition_status,
            "observed_competitor_count": competition_evidence.observed_competitor_count if competition_evidence else 0,
            "offers": [offer.to_dict() for offer in competition_evidence.offers] if competition_evidence else [],
            "warnings": list(competition_evidence.warnings) if competition_evidence else [],
        },
        "margin_intelligence": margin.to_dict() if margin else None,
        "opportunity_scoring": run.metadata.get("opportunity_assessment"),
        "product_research_portfolio": portfolio.to_dict(),
        "commerce_mvp_run": {"run_id": run.run_id, "status": run.status, "selected_candidate": run.selected_candidate.product_name if run.selected_candidate else None},
        "canonical_event_ids": list(run.canonical_event_ids) + [event.event_id for event in research_events],
        "canonical_event_types": sorted({event.event_type for event in replayed_events}),
        "api_dashboard_read_path": {
            "events_path": str(events_path.relative_to(ROOT)) if events_path.is_relative_to(ROOT) else str(events_path),
            "events_replayed": len(replayed_events), "replay_warnings": replay_warnings,
            "commerce_runs_readable": len(read_report["commerce_runs"]) > 0,
            "opportunity_rankings_readable": len(read_report["opportunity_rankings"]) > 0,
            "competition_summaries_readable": len(read_report["competition_summaries"]) > 0,
            "research_portfolios_readable": len(read_report["research_portfolios"]) > 0,
        },
        "status": overall_status,
        "next_action": next_action,
        "read_only": True, "advisory": True, "mutated": False,
        "no_supplier_mutation_authority": True, "no_order_authority": True,
    }

    (out_dir / "validation_report.json").write_text(json.dumps(report, sort_keys=True, indent=2), encoding="utf-8")
    if args.markdown:
        (out_dir / "validation_report.md").write_text(_markdown(report), encoding="utf-8")

    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 1 live validation report", "", f"- Status: `{report['status']}`", f"- Generated: {report['generated_at']}",
        f"- Query: `{report['input_urls']['query']}`", f"- Supplier URL: `{report['input_urls']['supplier_url'] or 'none'}`",
        f"- Competitor URLs: {len(report['input_urls']['competitor_urls'])}", "",
        "## Network diagnosis", "",
    ]
    for diag in report["network_status"]["diagnosis"]:
        lines.append(f"- `{diag['hostname']}`: {diag['failure_mode']} — {diag.get('detail', '')}")
    lines += ["", "## Evidence", "", f"- Supplier: {report['supplier_evidence']['status']}", f"- Competition: {report['competition_evidence']['status']}", "",
              "## Read path", "", f"- Events replayed: {report['api_dashboard_read_path']['events_replayed']}",
              f"- commerce_runs readable: {report['api_dashboard_read_path']['commerce_runs_readable']}",
              f"- opportunity_rankings readable: {report['api_dashboard_read_path']['opportunity_rankings_readable']}",
              f"- competition_summaries readable: {report['api_dashboard_read_path']['competition_summaries_readable']}",
              f"- research_portfolios readable: {report['api_dashboard_read_path']['research_portfolios_readable']}", "",
              "## Next action", "", report["next_action"], ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
