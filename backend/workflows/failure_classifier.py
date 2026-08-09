def classify_workflow_failure(stage_name,exc_or_error,context=None):
 text=str(exc_or_error).lower();ctx=context or {};category="unexpected_exception";severity="error";retryable=False;recoverable=False;action=True
 if "path" in text and ("unsafe" in text or "escape" in text):category="unsafe_path";severity="critical"
 elif "parser" in text:category="unsupported_parser"
 elif "evidence" in text and ("no_" in text or "missing" in text or "no evidence" in text):category="no_evidence";severity="warning";recoverable=True;retryable=True
 elif "unavailable" in text:category="unavailable_service";recoverable=True
 elif "blocked" in text or "live" in text or "mutation" in text:category="blocked_by_safety";severity="critical"
 elif "obsidian" in text:category="obsidian_unconfigured";severity="warning";action=False;recoverable=True
 elif "registry" in text:category="registry_unavailable";recoverable=True
 elif "artifact" in text:category="artifact_render_failed";recoverable=True
 elif "validation" in text:category="validation_failed";recoverable=True
 return {"category":category,"severity":severity,"retryable":retryable and category!="blocked_by_safety","recoverable":recoverable,"operator_action_required":action,"message":str(exc_or_error),"next_actions":["Review the stage inputs and rerun the safe stage."],"metadata":{"stage_name":stage_name,**ctx}}
