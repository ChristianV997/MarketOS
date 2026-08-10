"""Deterministic, read-only canonical event queries for JSONL and adapters."""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence
from backend.contracts.events import Event
from .query_models import CommerceRunSummary, CompetitionSummary, EventQuery, EventRecordView, EventTimeline, OpportunityRankingSummary, ResearchPortfolioSummary, ShopifyImportSummary

def load_events_from_jsonl(path: str | Path) -> tuple[list[Event], list[str]]:
    events: list[Event] = []; warnings: list[str] = []
    try: lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError: return events, ["jsonl_file_unavailable"]
    for index, line in enumerate(lines, 1):
        try: events.append(Event.from_dict(json.loads(line)))
        except Exception: warnings.append(f"malformed_jsonl_row:{index}")
    return events, warnings

def query_events(events: Sequence[Event], query: EventQuery) -> list[Event]:
    def matched(event: Event) -> bool:
        return all((value is None or getattr(event, field) == value) for field, value in (("workspace_id", query.workspace_id), ("event_type", query.event_type), ("aggregate_type", query.aggregate_type), ("aggregate_id", query.aggregate_id), ("correlation_id", query.correlation_id), ("source", query.source))) and (query.since is None or event.occurred_at >= query.since) and (query.until is None or event.occurred_at <= query.until)
    values = sorted((event for event in events if matched(event)), key=lambda item: (item.occurred_at, item.event_id), reverse=query.sort == "desc")
    return values[query.offset:query.offset + query.limit]

def _summary(value: dict[str, Any]) -> dict[str, Any]:
    return {"keys": sorted(value), "item_count": len(value)}

def summarize_event_record(event: Event) -> EventRecordView:
    flags = tuple(sorted(key for key, value in event.metadata.items() if value is True and (key.startswith("no_") or key in {"manual_approval_required", "non_authoritative"})))
    return EventRecordView(event.event_id, event.workspace_id, event.event_type, event.aggregate_type, event.aggregate_id, event.occurred_at, event.source, event.correlation_id, event.causation_id, event.replay_hash(), _summary(event.payload), _summary(event.metadata), bool(event.metadata.get("dry_run")), bool(event.metadata.get("advisory")), bool(event.metadata.get("read_only")), bool(event.metadata.get("pii_redacted")), flags)

def build_event_timeline(events: Sequence[Event], query: EventQuery, warnings: Sequence[str] = ()) -> EventTimeline:
    selected = query_events(events, query); views = tuple(summarize_event_record(event) for event in selected)
    return EventTimeline(query.workspace_id, views, dict(sorted(Counter(event.event_type for event in selected).items())), dict(sorted(Counter(event.aggregate_type for event in selected).items())), min((event.occurred_at for event in selected), default=None), max((event.occurred_at for event in selected), default=None), tuple(warnings))

def build_commerce_run_summaries(events: Sequence[Event]) -> list[CommerceRunSummary]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.event_type.startswith("commerce_mvp_"): groups[event.correlation_id or event.aggregate_id].append(event)
    summaries: list[CommerceRunSummary] = []
    for run_id, rows in sorted(groups.items()):
        start = next((item for item in rows if item.event_type == "commerce_mvp_run_started"), rows[0]); complete = next((item for item in rows if item.event_type == "commerce_mvp_run_completed"), None); selected = next((item for item in rows if item.event_type == "commerce_mvp_candidate_selected"), None)
        types = {item.event_type for item in rows}; payload = complete.payload if complete else {}
        summaries.append(CommerceRunSummary(start.workspace_id, run_id, str(start.payload.get("query", "")), str(payload.get("status", "incomplete")), sum(item.event_type == "commerce_mvp_opportunity_candidate_created" for item in rows), str(selected.payload.get("product_name")) if selected else None, "commerce_mvp_unit_economics_estimated" in types, "commerce_mvp_creative_packet_created" in types, "commerce_mvp_landing_page_packet_created" in types, "commerce_mvp_store_draft_packet_created" in types, "commerce_mvp_manual_approval_packet_created" in types, "commerce_mvp_vendor_recommendations_attached" in types, len(rows), tuple(payload.get("warnings", ())), tuple(payload.get("blockers", ()))) )
    return summaries

def build_shopify_import_summaries(events: Sequence[Event]) -> list[ShopifyImportSummary]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.event_type.startswith("shopify_"):
            batch_id = str(event.metadata.get("import_batch_id") or event.correlation_id or event.aggregate_id); groups[batch_id].append(event)
    summaries: list[ShopifyImportSummary] = []
    for batch_id, rows in sorted(groups.items()):
        context = next((item.payload for item in rows if item.event_type == "shopify_store_context_built"), {}); completed = next((item.payload for item in rows if item.event_type == "shopify_import_batch_completed"), {}); workspace = rows[0].workspace_id
        count = lambda name: sum(item.event_type == name for item in rows)
        summaries.append(ShopifyImportSummary(workspace, batch_id, int(context.get("product_count", count("shopify_product_observed"))), int(context.get("variant_count", count("shopify_variant_observed"))), int(context.get("collection_count", count("shopify_collection_observed"))), int(context.get("order_count", count("shopify_order_observed"))), int(context.get("line_item_count", count("shopify_line_item_observed"))), int(context.get("customer_count", count("shopify_customer_observed"))), bool(context.get("pii_redacted", all(item.metadata.get("pii_redacted") for item in rows))), float(context.get("observed_revenue_total", 0.0)), float(context.get("average_order_value", 0.0)), len(rows), tuple(completed.get("warnings", ()))) )
    return summaries

def build_opportunity_ranking_summaries(events: Sequence[Event]) -> list[OpportunityRankingSummary]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.event_type in {"opportunity_scoring_started", "candidate_scored", "opportunity_ranked", "opportunity_scoring_completed"}:
            groups[event.correlation_id or event.aggregate_id].append(event)
    summaries: list[OpportunityRankingSummary] = []
    for run_id, rows in sorted(groups.items()):
        start = next((item for item in rows if item.event_type == "opportunity_scoring_started"), rows[0])
        ranked = next((item for item in rows if item.event_type == "opportunity_ranked"), None)
        scored = [item.payload for item in rows if item.event_type == "candidate_scored"]
        order = list(ranked.payload.get("ranking", [])) if ranked else []
        if order:
            rank_index = {candidate_id: position for position, candidate_id in enumerate(order)}
            scored = sorted(scored, key=lambda item: rank_index.get(item.get("candidate_id"), len(order)))
        top_candidate_id = ranked.payload.get("top_candidate_id") if ranked else None
        summaries.append(OpportunityRankingSummary(start.workspace_id, run_id, str(start.payload.get("query", "")), top_candidate_id, len(scored), tuple(scored), len(rows)))
    return summaries

def build_competition_summaries(events: Sequence[Event]) -> list[CompetitionSummary]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.event_type in {"competition_observed", "competition_summary_created", "market_pricing_computed", "market_intelligence_completed"}:
            groups[event.correlation_id or event.aggregate_id].append(event)
    summaries: list[CompetitionSummary] = []
    for run_id, rows in sorted(groups.items()):
        summary_event = next((item for item in rows if item.event_type == "competition_summary_created"), None)
        pricing_event = next((item for item in rows if item.event_type == "market_pricing_computed"), None)
        offers = [item.payload for item in rows if item.event_type == "competition_observed"]
        payload = summary_event.payload if summary_event else {}
        workspace = rows[0].workspace_id
        summaries.append(CompetitionSummary(
            workspace, run_id, str(payload.get("query", "")),
            int(payload.get("observed_competitor_count", 0)), payload.get("observed_median_price"),
            payload.get("market_saturation"), str(payload.get("market_maturity", "unknown")),
            float(payload.get("confidence", 0.0)), tuple(offers),
            pricing_event.payload if pricing_event else None, len(rows),
        ))
    return summaries

def build_research_portfolio_summaries(events: Sequence[Event]) -> list[ResearchPortfolioSummary]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.event_type in {"candidate_discovered", "candidate_clustered", "research_portfolio_updated", "ranking_changed", "research_completed"}:
            groups[event.correlation_id or event.aggregate_id].append(event)
    summaries: list[ResearchPortfolioSummary] = []
    for run_id, rows in sorted(groups.items()):
        portfolio_event = next((item for item in rows if item.event_type == "research_portfolio_updated"), None)
        clusters = [item.payload for item in rows if item.event_type == "candidate_clustered"]
        movements = [item.payload for item in rows if item.event_type == "ranking_changed"]
        payload = portfolio_event.payload if portfolio_event else {}
        workspace = rows[0].workspace_id
        summaries.append(ResearchPortfolioSummary(
            workspace, run_id, payload.get("top_candidate_id"), int(payload.get("candidate_count", 0)),
            int(payload.get("cluster_count", len(clusters))), payload.get("quality"),
            dict(payload.get("bucket_counts", {})), tuple(clusters), tuple(movements), len(rows),
        ))
    return summaries

def event_query_report(events: Sequence[Event], query: EventQuery, warnings: Sequence[str] = ()) -> dict[str, Any]:
    timeline = build_event_timeline(events, query, warnings)
    return {"query": query.to_dict(), "timeline": timeline.to_dict(), "commerce_runs": [item.to_dict() for item in build_commerce_run_summaries(query_events(events, query))], "shopify_imports": [item.to_dict() for item in build_shopify_import_summaries(query_events(events, query))], "opportunity_rankings": [item.to_dict() for item in build_opportunity_ranking_summaries(query_events(events, query))], "competition_summaries": [item.to_dict() for item in build_competition_summaries(query_events(events, query))], "research_portfolios": [item.to_dict() for item in build_research_portfolio_summaries(query_events(events, query))], "read_only": True, "network_calls": False, "mutated": False}

__all__ = ["build_commerce_run_summaries", "build_competition_summaries", "build_event_timeline", "build_opportunity_ranking_summaries", "build_research_portfolio_summaries", "build_shopify_import_summaries", "event_query_report", "load_events_from_jsonl", "query_events", "summarize_event_record"]
