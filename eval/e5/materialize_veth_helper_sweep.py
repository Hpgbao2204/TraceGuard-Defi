#!/usr/bin/env python3
import hashlib, json
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/dose_100.json'
OUT=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/helper_coupled_sweep_295_290.json'

def word(s,i): return int(s[10+i*64:10+(i+1)*64],16)
def sig(tx):
    c=[(e.get('event'),e.get('depth'),e.get('type'),e.get('from','').lower(),e.get('to','').lower(),e.get('input','')[:10].lower()) for e in tx['call_trace']]
    l=[(x.get('address','').lower(),tuple(x.get('topics',[]))) for x in tx.get('logs',[])]
    return c,l
def load(p): return json.loads(Path(p).read_text())['per_tx'][57]
def main():
    b=load(BASE); bc,bl=sig(b); rows=[]
    for dose in (295,290):
        raw=Path(f'/tmp/veth-helper-{dose}.json'); tx=load(raw); c,l=sig(tx)
        mint=next(e for e in tx['call_trace'] if e.get('event')=='enter' and e.get('input','').startswith('0x9e358be1'))
        tf=next(e for e in tx['call_trace'] if e.get('event')=='enter' and e.get('input','').startswith('0x23b872dd') and e.get('from','').lower()=='0x62f250cf7021e1cf76c765dec8ec623fe173a1b5'.lower())
        cashin=Decimal('5426.700593482696725462'); success=bool(tx.get('actual_status'))
        row={'dose_token0':dose,'mint_token0_raw':str(word(mint['input'],1)),'transfer_from_token1_raw':str(word(tf['input'],2)),'actual_status':tx.get('actual_status'),'gas_match':tx.get('gas_match'),'status_match':tx.get('status_match'),'logs_match':tx.get('logs_match'),'post_state_match':tx.get('post_state_match'),'acceptance_gate':json.loads(raw.read_text()).get('acceptance_gate'),'topology_preserved':bool(success and c==bc and l==bl),'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}
        if success:
            cashout=Decimal(tx['call_trace'][99]['value'])/Decimal(10**18); row.update({'cashout_eth':str(cashout),'profit_eth':str(cashout-cashin)})
        else:
            row['cashout_eth']=None; row['profit_eth']=None; row['classification']='FEASIBILITY_BOUNDARY_REVERT_NOT_A_PROFIT_OBSERVATION'
        rows.append(row)
    out={'status':'COUPLED_DOSE_SWEEP_DIAGNOSTIC_WITH_FEASIBILITY_BOUNDARY','case_id':'defihacklabs-veth-2024-11-14','baseline_profit_eth':'4.846141416396402693','points':rows,'interpretation':'Dose 295 executes with preserved topology and reduced diagnostic profit. Dose 290 reverts and therefore has no valid cashout/profit observation; it marks a feasibility boundary. Results remain diagnostic only and do not establish protected-harm causality.','baseline_raw_sha256':hashlib.sha256(BASE.read_bytes()).hexdigest()}
    OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT); print(hashlib.sha256(OUT.read_bytes()).hexdigest())
if __name__=='__main__': main()
