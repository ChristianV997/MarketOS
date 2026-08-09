"""Read-only migration readiness report for canonical golden replay fixtures."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DEFAULT=ROOT/"tests/fixtures/golden_replay"
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from backend.events.replay_certification import build_migration_readiness_report,load_canonical_jsonl
def main():
 p=argparse.ArgumentParser();p.add_argument("--fixtures",action="store_true");p.add_argument("--path",action="append",default=[]);p.add_argument("--output");args=p.parse_args();paths=[Path(x) for x in args.path] or (sorted(DEFAULT.glob("*.jsonl")) if args.fixtures or not args.path else [])
 reports={str(path):build_migration_readiness_report(load_canonical_jsonl(path)) for path in paths};output={"fixture_count":len(reports),"reports":reports}
 text=json.dumps(output,sort_keys=True,indent=2)
 if args.output:Path(args.output).parent.mkdir(parents=True,exist_ok=True);Path(args.output).write_text(text+"\n",encoding="utf-8")
 print(text)
if __name__=="__main__":main()
