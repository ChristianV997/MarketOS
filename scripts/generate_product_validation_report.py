from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from evaluation.commerce.product_validation_report import generate,markdown
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--client-name',default='');p.add_argument('--marketplace-trend-report');p.add_argument('--supplier-feasibility-report');p.add_argument('--consumer-attention-report');p.add_argument('--output');p.add_argument('--json',action='store_true');p.add_argument('--markdown',action='store_true');a=p.parse_args(argv)
 if a.json and a.markdown:p.error('choose --json or --markdown')
 trends=None; supplier=None; attention=None
 if a.marketplace_trend_report:
  trends=json.loads(Path(a.marketplace_trend_report).read_text(encoding='utf8'))
 if a.supplier_feasibility_report:
  supplier=json.loads(Path(a.supplier_feasibility_report).read_text(encoding='utf8'))
 if a.consumer_attention_report:
  attention=json.loads(Path(a.consumer_attention_report).read_text(encoding='utf8'))
 r=generate(client_name=a.client_name,marketplace_trends=trends,supplier_feasibility=supplier,consumer_attention=attention).to_dict();md=markdown(r)
 if a.output:
  d=Path(a.output);d.mkdir(parents=True,exist_ok=True);(d/'product_validation_report.json').write_text(json.dumps(r,indent=2),encoding='utf8');(d/'product_validation_report.md').write_text(md,encoding='utf8');(d/'sales_summary.md').write_text(f"# Sales Summary\n\nOffer a Product Validation Report for {r['pricing_guidance']['suggested_report_range_usd']}.\n\nHook: {r['executive_summary']['headline']}\n\nUpsell: {r['pricing_guidance']['upsell']}\n",encoding='utf8');(d/'internal_summary.json').write_text(json.dumps({'recommendation':r['overall_recommendation'],'next':r['recommended_next_actions']},indent=2),encoding='utf8')
 print(md if a.markdown else json.dumps(r,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
