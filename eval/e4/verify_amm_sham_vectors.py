import json
from pathlib import Path
from eval.b2_run_select import select_canonical_run
from eval.e4.vector_from_replay import vector
ROOT=Path(__file__).resolve().parents[2]
PILOTS=['defihacklabs-rnspay-2025-03-06','defihacklabs-sbr-token-2025-03-07']
def main():
    man={x['case_id']:x for x in json.load(open(ROOT/'docs/m4_frozen_case_manifest.json'))['cases']}; results=[]; infra=['0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2']
    for cid in PILOTS:
        c=man[cid]; ctx=ROOT/'eval/results/m4/b2-contexts-fresh'/cid; base=select_canonical_run(ctx,c['tx_hash']); sham=json.load(open(ROOT/'eval/results/e4_causal_v4/replays'/cid/'same_kind_observe_only.json'))['per_tx'][c['tx_index']]
        bv,_,_=vector(base,infra); sv,_,_=vector(sham,infra); results.append({'case_id':cid,'vector_equal':bv.json()==sv.json(),'baseline_vector':bv.json(),'sham_vector':sv.json(),'execution_preserved':all(sham.get(k) is True for k in ('status_match','logs_match','post_state_match')) and sham.get('actual_gas')==base.get('actual_gas'),'match_count':(sham.get('call_intervention') or {}).get('match_count')})
    out=ROOT/'eval/results/e4_causal_v4/amm_sham_vector_verification.json'; out.write_text(json.dumps({'schema_version':1,'scope':'frozen-20 AMM same-kind sham vector verification','cases':results,'gate4_vector_pass':all(x['vector_equal'] for x in results)},indent=2)+'\n'); print(json.dumps({'cases':len(results),'vector_equal':sum(x['vector_equal'] for x in results),'execution_exact':sum(x['execution_preserved'] for x in results)}))
if __name__=='__main__': main()
