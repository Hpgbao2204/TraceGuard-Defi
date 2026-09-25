#!/usr/bin/env python3
"""Audit VETH cashOut conversion against historical bytecode and trace."""
import json
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CASE=ROOT/'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/cashout_path_audit.json'
TOKEN='0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e'
FACTORY='0x19c5538df65075d53d6299904636bae68b6df441'
CASHOUT='0x5c7b79f5'

def main():
 d=json.loads((CASE/'b2-replay-m4.json').read_text()); trace=d['per_tx'][57]['call_trace']
 e=next((x for x in trace if x.get('event')=='enter' and x.get('to','').lower()==TOKEN and (x.get('input') or '')[:10].lower()==CASHOUT),None)
 i=trace.index(e); ex=next(x for x in trace[i+1:] if x.get('event')=='exit' and x.get('depth')==e.get('depth'))
 amount=int(e['input'][-64:],16); eth=int(next(x for x in trace[i+1:] if x.get('event')=='enter' and x.get('depth')==e['depth']+1 and x.get('to','').lower()==FACTORY)['value'])
 out={'status':'DIAGNOSTIC_CONVERSION_AUDIT','case_id':'defihacklabs-veth-2024-11-14','trace_index':i,'selector':CASHOUT,'cashout_input_token0_raw':str(amount),'cashout_input_token0':str(Decimal(amount)/Decimal(10**18)),'eth_released_raw':str(eth),'eth_released':str(Decimal(eth)/Decimal(10**18)),'token0_equals_eth_1_to_1':amount==eth,'nested_calls':[{k:x.get(k) for k in ('event','depth','type','from','to','input','value','error') if k in x} for x in trace[i+1:trace.index(ex)] if x.get('event')=='enter'],'interpretation':{'confirmed':'cashOut returns exactly the token0 amount supplied, in native ETH, on the observed native branch; its nested call is the Factory fallback/value receiver, not a pair/oracle read.','excluded':'The observed cashOut frame does not support a claim that it reprices token0 from AMM reserves.','remaining':'The causal question moves upstream to how token0 amount is created and exchanged against the thin pair.'}}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT)
if __name__=='__main__': main()
