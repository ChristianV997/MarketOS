from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from evaluation.commerce.product_validation_report import generate,markdown
def _read_report(value):
 if not value:return None
 target=Path(value)
 if ".." in target.parts or target.suffix.lower() != '.json':raise ValueError('only local JSON report paths without traversal are supported')
 return json.loads(target.read_text(encoding='utf8'))
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--client-name',default='');p.add_argument('--marketplace-trend-report');p.add_argument('--supplier-feasibility-report');p.add_argument('--consumer-attention-report');p.add_argument('--opportunity-synthesis-report');p.add_argument('--output');p.add_argument('--json',action='store_true');p.add_argument('--markdown',action='store_true');a=p.parse_args(argv)
 if a.json and a.markdown:p.error('choose --json or --markdown')
 trends=None; supplier=None; attention=None; synthesis=None
 try:
  trends=_read_report(a.marketplace_trend_report)
  supplier=_read_report(a.supplier_feasibility_report)
  attention=_read_report(a.consumer_attention_report)
  synthesis=_read_report(a.opportunity_synthesis_report)
 except (OSError,ValueError,json.JSONDecodeError) as exc:
  p.error(str(exc))
 r=generate(client_name=a.client_name,marketplace_trends=trends,supplier_feasibility=supplier,consumer_attention=attention,opportunity_synthesis=synthesis).to_dict();md=markdown(r)
 if a.output:
  d=Path(a.output);d.mkdir(parents=True,exist_ok=True);(d/'product_validation_report.json').write_text(json.dumps(r,indent=2),encoding='utf8');(d/'product_validation_report.md').write_text(md,encoding='utf8');(d/'sales_summary.md').write_text(f"# Sales Summary\n\nOffer a Product Validation Report for {r['pricing_guidance']['suggested_report_range_usd']}.\n\nHook: {r['executive_summary']['headline']}\n\nUpsell: {r['pricing_guidance']['upsell']}\n",encoding='utf8');(d/'internal_summary.json').write_text(json.dumps({'recommendation':r['overall_recommendation'],'next':r['recommended_next_actions']},indent=2),encoding='utf8')
 print(md if a.markdown else json.dumps(r,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
