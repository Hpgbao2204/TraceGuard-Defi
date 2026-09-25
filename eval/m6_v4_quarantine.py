"""Record failed B2 run files without deleting or modifying them."""
import json
from pathlib import Path
from eval.corpus_authority import assert_frozen20
ROOT=Path(__file__).resolve().parents[1]
def main():
    man=json.loads((ROOT/'docs/m4_frozen_case_manifest.json').read_text())['cases']; out=[]
    for c in man:
        context=ROOT/'eval/results/m4/b2-contexts-fresh'/c['case_id']
        for p in context.glob('b2-run-*.json'):
            d=json.loads(p.read_text()); rows=[r for r in d.get('per_tx',[]) if r.get('tx_hash','').lower()==c['tx_hash'].lower()]
            if rows:
                r=rows[0]; ok=all(r.get(k) is True for k in ('gas_match','status_match','logs_match')) and d.get('isolated_baseline_gate') is True
                if not ok: out.append({'case_id':c['case_id'],'run':p.name,'gate':False})
    meta=assert_frozen20([x['case_id'] for x in man],'frozen-20'); dest=ROOT/'eval/results/e4_causal_v4/b2_run_quarantine.json'; dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps({'schema_version':1,'scope':'frozen-20 B2 failed-run quarantine',**meta,'count':len(out),'runs':out},indent=2)+'\n'); print(json.dumps({'failed_runs':len(out)}))
if __name__=='__main__': main()
