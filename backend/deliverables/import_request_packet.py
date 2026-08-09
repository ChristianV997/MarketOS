from .package import DeliverableSection
from backend.discovery.acquisition_registry import get_acquisition_registry
def build_import_request_packet(workspace_id="default",package_id=None,max_requests=8):
    plans=get_acquisition_registry().list_plans(workspace_id,limit=max(0,min(int(max_requests),20))); lines=[]; refs=[]
    for plan in plans:
        step=plan.steps[0] if plan.steps else None; lines.append(f"### {plan.title}\n\n**Why:** {plan.objective}\n\n- Parser: `{plan.parser_type}`\n- Template: `{', '.join(plan.template_paths) or 'not created'}`\n- Required fields: {', '.join(step.required_fields if step else [])}\n- Optional fields: {', '.join(step.optional_fields if step else [])}\n- Mode: `{plan.current_mode}`; no live connector is enabled.")
        refs.append({"type":"acquisition_plan","id":plan.plan_id,"parser_type":plan.parser_type})
    content="## Import requests\n\n"+("\n\n".join(lines) or "No acquisition plans are currently available. Run refinement first.")+"\n\nUpload only authorized local/cache exports; do not include secrets or personal data."
    return DeliverableSection("import_requests","Recommended Evidence Imports",9,content,"Actionable evidence requests",refs,warnings=[])
