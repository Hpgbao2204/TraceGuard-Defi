"""V4 AMM pilot baseline gate; mutation is intentionally not implicit."""
import json
from pathlib import Path
from eval.b2_adapter import run as run_b2
from eval.b2_run_select import select_canonical_run
from eval.corpus_authority import assert_frozen20
ROOT=Path(__file__).resolve().parents[2]
PILOTS={'defihacklabs-rnspay-2025-03-06','defihacklabs-sbr-token-2025-03-07'}
def main():
    man=json.loads((ROOT/'docs/m4_frozen_case_manifest.json').read_text())['cases']; b2={x['case_id']:x for x in json.loads((ROOT/'eval/results/m6_b2_preflight.json').read_text())['cases']}; desc=json.loads((ROOT/'eval/results/e4_causal_v4/m6_amm_reserve_descriptors.json').read_text())['cases']; dm={x['case_id']:x for x in desc}; rows=[]
    for c in man:
        if c['case_id'] not in PILOTS: continue
        context=b2[c['case_id']]['context']; fresh=run_b2(context,timeout=900)
        try: canonical=select_canonical_run(context,c['tx_hash']); status='BASELINE_READY'
        except Exception as e: canonical=None; status='BASELINE_GATE_FAIL:'+type(e).__name__
        rows.append({'case_id':c['case_id'],'descriptor':dm.get(c['case_id']), 'fresh_b2_acceptance':bool(fresh.payload.get('acceptance_gate')),'canonical_run':canonical.get('_run_name') if canonical else None,'status':status,'mutation_executed':False,'sham_executed':False})
    meta=assert_frozen20([x['case_id'] for x in man],'frozen-20'); out=ROOT/'eval/results/e4_causal_v4/amm_pilot_v4_preflight.json'; out.write_text(json.dumps({'schema_version':1,'scope':'frozen-20 AMM pilot v4 preflight',**meta,'resolver_versions':{'run_select':'v1','amm_descriptor':'v1','harm':'t0-v2'},'cases':rows,'causal_replay_executed':False},indent=2)+'\n'); print(json.dumps({'cases':len(rows),'baseline_ready':sum(x['status']=='BASELINE_READY' for x in rows)}))
if __name__=='__main__': main()
