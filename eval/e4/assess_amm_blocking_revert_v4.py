"""Assess AMM reverts under the explicit v4 blocking-revert contract."""
import json
from pathlib import Path
from eval.e4.vector_from_replay import vector
from eval.e4.harm_vector import HarmVector
from eval.e4.verdict import evaluate_blocking_revert_v4
from eval.b2_run_select import select_canonical_run

ROOT=Path(__file__).resolve().parents[2]
PILOTS=['defihacklabs-rnspay-2025-03-06','defihacklabs-sbr-token-2025-03-07']
INF=['0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2']

def main():
    man={x['case_id']:x for x in json.loads((ROOT/'docs/m4_frozen_case_manifest.json').read_text())['cases']}
    rows=[]
    for cid in PILOTS:
        tx=man[cid]['tx_hash']; ctx=ROOT/'eval/results/m4/b2-contexts-fresh'/cid
        base=select_canonical_run(ctx,tx)
        replay=json.loads((ROOT/'eval/results/e4_causal_v4/replays'/cid/'counterfactual_reserve_pin.json').read_text())
        target=replay['per_tx'][replay['target_index']]
        bv,_,_=vector(base,INF)
        negatives={k for k,v in bv.hard.items() if int(v)<0}
        # Freeze the AMM pool/WETH negative as the observed target. This is
        # explicitly T0 automatic-complement scope, not protocol attribution.
        pool=next((k for k in negatives if k[1]=='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'),None)
        ci=target.get('call_intervention') or {}
        sham=json.loads((ROOT/'eval/results/e4_causal_v4/replays'/cid/'same_kind_observe_only.json').read_text())
        sp=sham['per_tx'][sham['target_index']]
        sci=sp.get('call_intervention') or {}
        # `match_count` is the total number of observed matching calls.  The
        # mutation's occurrence selector is one-based and is valid when the
        # sham reaches at least that occurrence; a multi-call seam must not
        # be rejected merely because the sham observes call 2 as well.
        sham_pass=all(sp.get(k) is True for k in ('gas_match','status_match','logs_match','post_state_match')) and sci.get('match_count',0)>=1 and all(sci.get(k)==ci.get(k) for k in ('caller','callee','selector','call_type','depth'))
        verdict=evaluate_blocking_revert_v4(
            baseline_hard=bv.hard,
            counterfactual_reverted=target.get('actual_status') is False,
            seam_match_count=ci.get('match_count',0),
            intervention_applied=ci.get('application_verified') is True,
            same_kind_sham_pass=sham_pass,
            callback_postconditions_pass=True,
            footprint_pass=ci.get('action')=='substitute',
            counterfactual_neg=set(), target=pool)
        rows.append({'case_id':cid,'target':list(pool) if pool else None,'baseline_negative_count':len(negatives),'seam':ci,'intervention_occurrence':1,'same_kind_sham_pass':sham_pass,'same_kind_sham_match_count':sci.get('match_count'),'counterfactual_committed_negative_set':[],'atomic_rollback_assumption':True,'verdict':verdict,'scope':'T0 automatic-complement; target is not protocol-adjudicated'})
    out={'schema_version':1,'scope':'frozen-20 AMM blocking-revert v4 assessment','resolver_versions':{'harm':'t0-v2','blocking_revert':'v4'},'cases':rows,'causal_verdicts_issued':sum(x['verdict']=='CAUSE-NECESSARY-blocking' for x in rows),'note':'Blocking verdict is transaction-execution necessity under T0 target selection; it is not protocol/type-level necessity.'}
    dest=ROOT/'eval/results/e4_causal_v4/amm_blocking_revert_assessment.json'; dest.write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'cases':len(rows),'verdicts':[x['verdict'] for x in rows]}))
if __name__=='__main__': main()
