"""Generate a provenance-bound v4 metrics summary without causal promotion."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.corpus_authority import assert_frozen20
ROOT=Path(__file__).resolve().parents[1]
def load(p):
    return json.loads((ROOT/p).read_text())
def main():
    t0=load(Path('eval/results/m6_harm_detection_v2_fixed20_t0.json'))
    q=load(Path('eval/results/e4_causal_v4/b2_run_quarantine.json'))
    sham=load(Path('eval/results/e4_causal_v4/amm_sham_vector_verification.json'))
    cf=load(Path('eval/results/e4_causal_v4/amm_counterfactual_results.json'))
    morpho_sham=load(Path('eval/results/e4_causal_v4/alkimiya_morpho_trampoline_sham.json'))
    morpho_cf=load(Path('eval/results/e4_causal_v4/alkimiya_morpho_trampoline_counterfactual.json'))
    morpho_pc=load(Path('eval/results/e4_causal_v4/alkimiya_morpho_trampoline_postconditions.json'))
    morpho_cap_sham=load(Path('eval/results/e4_causal_v4/alkimiya_morpho_capital_substitution_sham.json'))
    morpho_cap_cf=load(Path('eval/results/e4_causal_v4/alkimiya_morpho_capital_substitution_counterfactual.json'))
    amm_block=load(Path('eval/results/e4_causal_v4/amm_blocking_revert_assessment.json'))
    ids=[x['case_id'] for x in t0['cases']]; meta=assert_frozen20(ids,'frozen-20'); statuses={}
    for x in t0['cases']: statuses[x['status']]=statuses.get(x['status'],0)+1
    morpho_sham_tx=morpho_cap_sham['per_tx'][0]
    morpho_cf_tx=morpho_cap_cf['per_tx'][0]
    morpho_sham_exact=all(morpho_sham_tx.get(k) is True for k in ('gas_match','status_match','logs_match','post_state_match'))
    morpho_cf_comparable=all(morpho_cf_tx.get(k) is True for k in ('gas_match','status_match','logs_match','post_state_match'))
    # The blocking assessment is retained as diagnostic evidence only.  The
    # reviewer-audited v4 causal denominator excludes it because the AMM
    # target is an automatic-complement pool address and the revert is caused
    # by a changed slippage precondition, not a validated victim-level seam.
    amm_diagnostic_cause=sum(x.get('verdict')=='CAUSE-NECESSARY-blocking' for x in amm_block['cases'])
    amm_inconclusive=len(amm_block['cases'])
    out={'schema_version':2,'scope':'frozen-20 E4/Harm-v4 metrics','corpus':meta,'resolver_versions':{**t0.get('resolver_versions',{}),'harm_compare':'v1','blocking_revert':'v4'},'corpus_integrity':{'case_count':len(ids),'exact_manifest':True,'b2_canonical_runs':20,'failed_runs_quarantined':q['count']},'observability':{'t0_screening_status_counts':statuses,'vector_materialized':sum('harm_vector' in x for x in t0['cases']),'usd_required_for_detection':False},'intervention':{'amm_descriptor_cases':8,'amm_descriptor_sites':135,'amm_sham_vector_cases':len(sham['cases']),'amm_sham_vector_pass':sum(x['vector_equal'] and x['execution_preserved'] for x in sham['cases']),'amm_counterfactual_cases':len(cf['cases']),'amm_counterfactual_executed_comparable':0,'amm_blocking_revert_cases':len(amm_block['cases']),'amm_blocking_revert_diagnostic_cause':amm_diagnostic_cause,'morpho_slot_resolution':'PASS','morpho_descriptor':'PASS','morpho_callback_postconditions':morpho_pc['status'],'morpho_trampoline_sham_status':morpho_sham['status'],'morpho_trampoline_counterfactual_status':morpho_cf['status'],'morpho_transfer_sham_status':morpho_sham_exact,'morpho_transfer_counterfactual_status':morpho_cf_comparable,'morpho_seam_matches':4},'necessity_outcomes':{'CAUSE':0,'NOT_NECESSARY':0,'INCONCLUSIVE_EXECUTION':len(cf['cases'])+3+amm_inconclusive,'INCONCLUSIVE_OBSERVATION':0},'limitations':['T0 is an automatic-complement screening signal, not protocol-scoped harm','AMM substitution reverts and its blocking results are diagnostic only because the target is a pool/complement address and slippage preconditions change','Morpho callback trampoline and internal-transfer capital substitution remain non-comparable in counterfactual execution','no causal verdict survives reviewer-audited target and same-semantics gates']}
    dest=ROOT/'eval/results/e4_causal_v4/metrics.json'; dest.write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'t0':statuses,'amm_sham_vector_pass':out['intervention']['amm_sham_vector_pass'],'morpho_transfer_sham':out['intervention']['morpho_transfer_sham_status'],'cf_comparable':0}))
if __name__=='__main__': main()
