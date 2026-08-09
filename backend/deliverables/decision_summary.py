def build_executive_summary(context):
    cards=context.get("scorecards",[]); advances=[]; holds=[]; rejects=[]; risks=[]; missing=[]
    for card in cards:
        data=card.to_dict() if hasattr(card,"to_dict") else card; item={"opportunity_id":data.get("opportunity_id"),"name":data.get("opportunity_name"),"score":data.get("validation_score"),"confidence":data.get("confidence"),"reason":data.get("recommendation")}
        if data.get("recommendation")=="advance_to_launch_candidate": advances.append(item)
        elif data.get("recommendation")=="reject": rejects.append(item)
        else: holds.append(item)
        risks.extend(data.get("risk_flags",[])); missing.extend(data.get("missing_evidence",[]))
    limits=["This package uses only persisted local/cache/manual evidence and deterministic dry-run services.","No demand, sales, profitability, ROAS, or launch-readiness claim is made without supporting evidence."]
    summary=f"The sprint evaluated {len(cards)} opportunity scorecard(s). {len(advances)} support further planning, {len(holds)} require continued validation, and {len(rejects)} are rejected by the recorded gates."
    return {"summary":summary,"top_recommendations":["Review advance candidates manually before any launch decision.","Close the highest-priority evidence gaps before scaling validation."],"advance":advances,"hold":holds,"reject":rejects,"risks":sorted(set(risks)),"missing_evidence":sorted(set(missing)),"next_actions":["Review the scorecards and provenance.","Import recommended evidence and rerun refinement."],"limitations":limits}
