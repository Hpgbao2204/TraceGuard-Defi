"""Build a prereplay dependency-operator matrix; never assigns a verdict."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SIDE=ROOT/'corpus/annotations/review_bundles_supplementary/m6_supplementary_adjudication_reviewer_c_v2.jsonl'
EVID=ROOT/'eval/results/m6_supplementary_display_evidence.json'
OUT=ROOT/'eval/results/m6_dependency_operator_matrix.json'
QUALIFIED={
 'defihacklabs-xlootstaking-2026-04-15': {
   'provider':'Balancer Vault', 'provider_address':'0xba12222222228d8ba445958a75a0704d566bf2c8',
   'primitive':'Balancer Vault flashLoan', 'selector':'0x5c38449e',
   'callback_selector':'0xf04f2707', 'boundary':'Balancer Vault -> receiver callback entry',
   'real_intervention':'neutralize the exact Balancer flashLoan call at provider boundary',
   'sham_intervention':'same provider-boundary instrumentation at the adjacent WETH repayment transfer',
   'sham_expected':'callback remains executable; financing remains available',
 },
 'defihacklabs-paraswapdaiapproval-2025-06-25': {
   'provider':'Balancer Vault', 'provider_address':'0xba12222222228d8ba445958a75a0704d566bf2c8',
   'primitive':'Balancer Vault flashLoan', 'selector':'0x5c38449e',
   'callback_selector':'0xf04f2707', 'boundary':'Balancer Vault -> receiver callback entry',
   'real_intervention':'neutralize the exact Balancer flashLoan call at provider boundary',
   'sham_intervention':'same provider-boundary instrumentation at the adjacent WETH repayment transfer',
   'sham_expected':'callback remains executable; financing remains available',
 },
 'defihacklabs-alkimiya-io-2025-03-28': {
   'provider':'Morpho', 'provider_address':'0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb',
   'primitive':'Morpho flash loan', 'selector':'0xe0232b42',
   'callback_selector':'0x31f57072', 'boundary':'Morpho -> loan callback entry',
   'real_intervention':'neutralize the exact Morpho flash-loan call at provider boundary',
   'sham_intervention':'same provider-boundary instrumentation on a non-callback token transfer',
   'sham_expected':'loan callback remains executable; financing remains available',
 },
 'defihacklabs-firetoken-2024-10-01': {
   'provider':'Aave V3', 'provider_address':'0xc13e21b648a5ee794902342038ff3adab66be987',
   'primitive':'Aave V3 flashLoanSimple', 'selector':'0x42b0b77c',
   'callback_selector':'0x1b11d0ff', 'boundary':'Aave V3 Pool -> receiver callback entry',
   'real_intervention':'neutralize the exact Aave flashLoanSimple call at provider boundary',
   'sham_intervention':'same provider-boundary instrumentation on a non-callback Pool call',
   'sham_expected':'receiver callback remains executable; financing remains available',
 },
 'defihacklabs-bankrollstackplus-2025-06-18': {'provider':'Uniswap V4','primitive':'unlock/take/settle flash accounting','boundary':'PoolManager unlock/settle boundary'},
 'defihacklabs-emptysetreserve-2025-07-24': {'provider':'Uniswap V4','primitive':'unlock/take/settle flash accounting','boundary':'PoolManager unlock/settle boundary'},
}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    side={json.loads(x)['case_id']:json.loads(x) for x in SIDE.read_text().splitlines() if x.strip()}
    ev={x['case_id']:x for x in json.loads(EVID.read_text())['cases']}
    rows=[]
    for cid in sorted(side):
        s=side[cid]; e=ev.get(cid,{})
        flash=s.get('flash_loan_role')
        q=QUALIFIED.get(cid, {}); provider=q.get('provider','unresolved'); v4=provider=='Uniswap V4'
        ready=(not v4 and all(q.get(k) for k in ('provider_address','selector','callback_selector','boundary','real_intervention','sham_intervention','sham_expected')))
        rows.append({'case_id':cid,'tx_hash':s['tx_hash'],'primitive':'flash_liquidity' if flash!='absent' else 'none_observed_by_reviewer','reviewed_flash_role':flash,'provider':provider,'provider_address':q.get('provider_address'),'observed_contracts':e.get('observed_contracts',[]),'observed_call_count':e.get('call_count',0),'primitive_semantics':q.get('primitive','unresolved'),'exact_selector':q.get('selector'),'callback_selector':q.get('callback_selector'),'expected_boundary':q.get('boundary','NOT_YET_PREREGISTERED'),'intervention_contract':q.get('real_intervention','provider-local neutralization; no generic f_fl substitution'),'sham_control':q.get('sham_intervention','PROVIDER_LOCAL_REQUIRED'),'sham_expected_behavior':q.get('sham_expected'),'accepted_evidence_fields':['baseline_fidelity','provider_frame','callback_boundary','real_intervention_application','expected_blocking_site','sham_executable','provenance'],'semantic_support':'D2_READY' if ready else ('PENDING_ADAPTER' if v4 else 'D2_PENDING'),'replay_authorized':ready,'dependency_verdict':'NOT_RUN'})
    ready_count=sum(r['semantic_support']=='D2_READY' for r in rows)
    out={'schema_version':3,'status':'D2_BOUNDARY_FREEZE_COMPLETE','release_scope_note':'This is execution dependency, not root-cause attribution. No dependency verdict maps to CAUSE.','outcome_taxonomy':{'DEPENDENCY_CONFIRMED':'neutralization passes semantic/application/control gates and blocks at preregistered boundary','DEPENDENCY_NOT_CONFIRMED':'valid intervention passes but exploit path remains executable','INCONCLUSIVE':'any gate, control, provenance, or comparability failure'},'source_sidecar_sha256':sha(SIDE),'source_evidence_sha256':sha(EVID),'source_trace_cache':'eval/results/e1_trace_cache.jsonl','cases':rows,'summary':{'dependency_testable':ready_count,'pending_provider_adapter':sum(r['semantic_support']=='PENDING_ADAPTER' for r in rows),'d2_ready':ready_count,'replay_authorized':ready_count==4}}
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps({'cases':len(rows),'status':out['status'],'out':str(OUT)},indent=2))
if __name__=='__main__': main()
