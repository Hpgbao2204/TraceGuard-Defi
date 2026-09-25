#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CASE=ROOT/'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/reorder_operator_precondition_audit.json'
def main():
    t=json.loads((CASE/'b2-replay-m4.json').read_text())['per_tx'][57]['call_trace']
    seq=[]
    for i in range(45,65):
        e=t[i]
        if e.get('event')=='enter': seq.append({'trace_index':i,'depth':e.get('depth'),'type':e.get('type'),'caller':e.get('from'),'callee':e.get('to'),'selector':(e.get('input') or '')[:10]})
    out={'status':'REORDER_OPERATOR_SPEC_PENDING_BACKEND_SUPPORT','case_id':'defihacklabs-veth-2024-11-14','historical_helper_window':{'entry':45,'exit':64,'position':'after primary swap trace 17-44 and before reverse settlement trace 77+'},'observed_preconditions':{'helper_sequence':seq,'reads_pair_reserves_before_mint':True,'calls_pair_mint':True,'calls_pair_sync':False,'reads_pair_balances_inside_pair_mint':True,'external_oracle_call_observed':False},'proposed_operator':{'name':'defer_virtual_liquidity_helper','semantics':'move the exact trace-45 helper call, preserving calldata/value/target, to after reverse settlement; do not scale amount, rewrite capital, pin reserves, or block helper','requires_new_backend_primitive':True,'same_kind_sham_required':True,'synthetic_state_required':True},'precondition_result':'The helper has no separately observed reserve-ratio guard before pair.mint, but pair.mint is state-sensitive and will execute against a different balance/reserve state after reordering. Therefore a reorder replay cannot be authorized as a simple call permutation until the backend can materialize the synthetic call order and validate pair.mint postconditions.','raw_sha256':hashlib.sha256((CASE/'b2-replay-m4.json').read_bytes()).hexdigest()}
    OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT); print(hashlib.sha256(OUT.read_bytes()).hexdigest())
if __name__=='__main__': main()
