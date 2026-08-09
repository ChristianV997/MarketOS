from __future__ import annotations
from pathlib import Path
from .package import DeliverablePackage,DeliverableArtifact
def render_deliverable_markdown(package): return package.to_markdown()
def render_deliverable_html(package): return "<!doctype html><html><head><meta charset='utf-8'><title>"+package.title.replace("<","&lt;")+"</title></head><body>"+package.to_html_fragment()+"</body></html>"
def write_deliverable_artifacts(package: DeliverablePackage, output_root="state/deliverables", formats=None):
    formats=formats or ["markdown","html"]; root=Path(output_root); root.mkdir(parents=True,exist_ok=True); artifacts=[]
    for fmt in formats:
        if fmt not in {"markdown","html"}: continue
        suffix="md" if fmt=="markdown" else "html"; path=(root/(package.package_id+"."+suffix)).resolve(); base=root.resolve()
        if base not in path.parents: raise ValueError("artifact path escapes output root")
        path.write_text(render_deliverable_markdown(package) if fmt=="markdown" else render_deliverable_html(package),encoding="utf-8")
        try: relative=str(path.relative_to(Path.cwd()))
        except ValueError: relative=str(path)
        artifact=DeliverableArtifact("artifact_"+package.package_id+"_"+fmt,"markdown_report" if fmt=="markdown" else "html_report",package.title,relative,"text/markdown" if fmt=="markdown" else "text/html",metadata={"package_id":package.package_id}); artifacts.append(artifact)
    return artifacts
