"""Check hosted Phase 1 read-only deployment readiness without network I/O."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from backend.deployment.readiness import build_readiness
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__); p.add_argument("--platform", default="local"); p.add_argument("--json", action="store_true"); p.add_argument("--markdown", action="store_true"); p.add_argument("--output"); a=p.parse_args(argv)
 if a.json and a.markdown: p.error("choose --json or --markdown")
 r=build_readiness(platform=a.platform).to_dict(); md=f"# Read-only deployment readiness\n\n- Status: `{r['overall_status']}`\n- Platform: `{r['platform']}`\n- Next: `{r['recommended_next_action']}`\n"
 if a.output:
  path=Path(a.output); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(md if a.markdown else json.dumps(r,indent=2,sort_keys=True)); return 0 if r["overall_status"] == "ready" else 1
if __name__=="__main__": raise SystemExit(main())
