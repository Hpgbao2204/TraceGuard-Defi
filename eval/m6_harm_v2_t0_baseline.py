"""Run T0 raw harm detection over frozen-20 factual B2 flow evidence."""
import json
from pathlib import Path
from eval.m6_harm_v2 import t0, SPEC
ROOT=Path(__file__).resolve().parents[1]
def main():
    src=json.loads((ROOT/'eval/results/m6_flashloan_harm_flow_batch.json').read_text())
    rows=[]
    for c in src['cases']:
        complete=c.get('status')=='FLOW_EXTRACTED' and isinstance(c.get('flows'),list) and isinstance(c.get('native_flows'),list)
        flows=c.get('flows',[])+[{'token':'eth','from':x['from'],'to':x['to'],'amount_raw':x['amount_raw']} for x in c.get('native_flows',[])]
        r=t0(flows,c.get('sender'),c.get('created_contracts',[]),complete)
        rows.append({'case_id':c['case'],'tx_hash':c.get('tx_hash'),
                     'raw_observation_complete': complete and r.status != 'UNKNOWN',
                     'evidence_complete': complete,
                     'valuation_required':False,'observation':r.json()})
    out={'schema_version':1,'detection_spec_id':SPEC,'tier':'T0','valuation_required':False,'causal_replay_executed':False,'cases':rows}
    p=ROOT/'eval/results/m6_harm_v2_t0_baseline.json'; p.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    from collections import Counter
    print(json.dumps(dict(Counter(x['observation']['status'] for x in rows)),indent=2))
if __name__=='__main__': main()
