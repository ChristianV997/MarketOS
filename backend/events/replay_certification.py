"""Read-only certification helpers for canonical event fixtures and adapters."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from backend.contracts.events import Event,InvalidCanonicalEvent
from .shadow_replay import classify_shadow_evidence

_LIVE=("live","publish","launch","spend","payment","order","fulfillment")
def load_canonical_jsonl(path):
    events=[]
    for number,line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        try:events.append(Event.from_dict(json.loads(line)))
        except Exception as exc:raise InvalidCanonicalEvent(f"{path}:{number}: {exc}") from exc
    return events
def hash_sequence(events):return [event.replay_hash() for event in events]
def validate_event_sequence(events):
    issues=[];previous=None;ids=set()
    for event in events:
        if event.event_id in ids:issues.append(f"duplicate_event_id:{event.event_id}")
        ids.add(event.event_id)
        if previous is not None and event.occurred_at<previous:issues.append(f"non_monotonic_timestamp:{event.event_id}")
        previous=event.occurred_at
        if not event.workspace_id:issues.append(f"missing_workspace_id:{event.event_id}")
    return issues
def assert_no_live_authority(events):
    violations=[]
    for event in events:
        if event.aggregate_type=="advisory":
            text=json.dumps({"event_type":event.event_type,"payload":event.payload,"metadata":event.metadata},sort_keys=True).lower()
            if any(token in text for token in _LIVE):violations.append(f"advisory_authority:{event.event_id}")
        if event.payload.get("live_authority") is True:violations.append(f"live_authority:{event.event_id}")
    return violations
def summarize_workflow(events):
    starts=[e for e in events if e.event_type=="workflow_started"];completed=[e.payload.get("step") for e in events if e.event_type=="step_completed"];failed=[e.payload.get("reason") or e.payload.get("step") for e in events if e.event_type in {"step_failed","step_blocked"}];terminal=next((e.event_type for e in reversed(events) if e.event_type in {"workflow_completed","workflow_failed"}),None)
    return {"workflow_count":len(starts),"completed_steps":completed,"failed_or_blocked":failed,"terminal_state":terminal}
def summarize_ledger(events):
    total=lambda kind:sum(float(e.payload.get("amount",0) or 0) for e in events if e.event_type==kind)
    revenue=total("order_created");cash=total("payment_captured")-total("refund_issued");supplier=total("supplier_cost_observed");spend=total("ad_spend_observed");refunds=total("refund_issued")
    claims={}
    for e in events:
        if e.event_type=="attribution_claim_observed":claims[e.payload.get("order_id")]=max(claims.get(e.payload.get("order_id"),0),float(e.payload.get("amount",0) or 0))
    return {"recognized_revenue":revenue,"cash_collected":cash,"supplier_cost":supplier,"ad_spend":spend,"refunds":refunds,"contribution_profit":revenue-supplier-spend-refunds,"attribution_claimed_revenue":sum(float(e.payload.get("amount",0) or 0) for e in events if e.event_type=="attribution_claim_observed"),"attribution_reconciled_revenue":sum(claims.values()),"roas":revenue/spend if spend else 0.0}
def summarize_shadow_flags(events):return [{"event_id":e.event_id,"metric_name":e.payload.get("metric_name"),**classify_shadow_evidence(e.payload)} for e in events if e.event_type=="shadow_evaluated"]
def summarize_advisory_artifacts(events):
    advisory=[e for e in events if e.aggregate_type=="advisory"]
    return {"artifact_count":len(advisory),"artifact_types":sorted(e.event_type for e in advisory),"authority_violations":assert_no_live_authority(advisory)}
def replay_summary(events):
    return {"event_count":len(events),"event_types":dict(sorted(Counter(e.event_type for e in events).items())),"aggregate_types":dict(sorted(Counter(e.aggregate_type for e in events).items())),"workspace_ids":sorted({e.workspace_id for e in events if e.workspace_id}),"sequence_issues":validate_event_sequence(events),"live_authority_violations":assert_no_live_authority(events),"workflow":summarize_workflow(events),"ledger":summarize_ledger(events),"shadow":summarize_shadow_flags(events),"advisory":summarize_advisory_artifacts(events),"hash_sequence":hash_sequence(events)}
def build_migration_readiness_report(events):
    summary=replay_summary(events);missing_correlation=[e.event_id for e in events if not e.correlation_id];missing_causation=[e.event_id for e in events[1:] if not e.causation_id];blockers=list(summary["sequence_issues"])+list(summary["live_authority_violations"])
    if missing_correlation:blockers.append("missing_correlation_ids")
    if missing_causation:blockers.append("missing_causation_ids")
    return {**summary,"missing_correlation_ids":missing_correlation,"missing_causation_ids":missing_causation,"migration_blockers":blockers,"recommended_next_step":"migrate_new_writes_only" if not blockers else "improve_envelope_completeness_before_migration"}
