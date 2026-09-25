"""Merge the four disjoint 20-case fidelity outputs and summarize outcomes."""
import csv, json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'eval/results/e5_rcfh/defihacklabs_80_fidelity_summary.json'
CSVOUT=ROOT/'eval/results/e5_rcfh/defihacklabs_80_fidelity.csv'
def main():
    rows=[]
    for i in range(4):
        with open(f'/tmp/defihacklabs_fidelity_{i}.csv',newline='') as f: rows.extend(csv.DictReader(f))
    assert len(rows)==80 and len({r['case'] for r in rows})==80
    rows.sort(key=lambda r:r['case'])
    fields=list(rows[0].keys())
    with CSVOUT.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    outcomes=Counter(r.get('outcome') for r in rows)
    reasons=Counter()
    for r in rows:
        note=(r.get('note') or '')+' '+(r.get('reason') or '')
        for key in ('warm-up','warmup','anvil_mine','429','chain ID','timeout','replay'):
            if key.lower() in note.lower(): reasons[key]+=1
    out={'schema_version':1,'artifact':'defihacklabs-80-fidelity-summary-v1','scope':'execution-level replay fidelity; no harm or causal verdict','case_count':80,'outcomes':dict(outcomes),'pass_count':sum(r.get('pass')=='True' for r in rows),'execution_pass_count':sum(r.get('execution_pass')=='True' for r in rows),'state_pass_count':sum(r.get('state_pass')=='True' for r in rows),'reason_keyword_counts':dict(reasons),'cases':rows,'interpretation':'PASS/fidelity outcomes are replay evidence only. UNOBSERVED and ERROR are abstentions; neither maps to HARM or NO_HARM.','next':'materialize raw transfer/native flows only for fidelity-accepted cases, then adjudicate protected entity before T0.'}
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'cases':80,'outcomes':dict(outcomes),'pass_count':out['pass_count'],'execution_pass_count':out['execution_pass_count'],'state_pass_count':out['state_pass_count']},indent=2))
if __name__=='__main__': main()
