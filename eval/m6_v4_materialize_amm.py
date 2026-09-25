"""Materialize frozen getReserves call-site descriptors, read-only."""
import json
from pathlib import Path
from eval.b2_run_select import select_canonical_run
from eval.corpus_authority import assert_frozen20
ROOT=Path(__file__).resolve().parents[1]
SEL='0x0902f1ac'; OUT=ROOT/'eval/results/e4_causal_v4/m6_amm_reserve_descriptors.json'
def main():
    man=json.loads((ROOT/'docs/m4_frozen_case_manifest.json').read_text())['cases']
    b2={x['case_id']:x for x in json.loads((ROOT/'eval/results/m6_b2_preflight.json').read_text())['cases']}
    rows=[]
    for c in man:
        try: row=select_canonical_run(b2[c['case_id']]['context'],c['tx_hash'])
        except Exception: continue
        sites=[]
        trace=row.get('call_trace') or []
        for i,x in enumerate(trace):
            if x.get('event')=='enter' and str(x.get('input','')).lower().startswith(SEL):
                exit_row=next((z for z in trace[i+1:] if z.get('event')=='exit' and z.get('depth')==x.get('depth')),{})
                sites.append({'trace_index':i,'depth':x.get('depth'),'caller':x.get('from'),'callee':x.get('to'),'selector':SEL,'returndata':exit_row.get('output')})
        if sites: rows.append({'case_id':c['case_id'],'pair_candidates':sorted({x['callee'] for x in sites}),'call_sites':sites,'canonical_run':row['_run_name'],'canonical_content_sha256':row['_content_sha256']})
    meta=assert_frozen20([x['case_id'] for x in man],'frozen-20'); OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({'schema_version':1,'scope':'frozen-20 AMM reserve descriptor preflight',**meta,'resolver_versions':{'run_select':'v1','amm_selector':'getReserves-v1'},'case_count':len(rows),'cases':rows},indent=2)+'\n')
    print(json.dumps({'descriptor_cases':len(rows),'sites':sum(len(x['call_sites']) for x in rows)}))
if __name__=='__main__': main()
