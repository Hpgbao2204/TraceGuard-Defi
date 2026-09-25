"""Compare the 80-case raw T0 batch with RCA reported-loss presence."""
import json
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2]
T0=ROOT/'eval/results/e5_rcfh/defihacklabs_80_t0_raw.json'
RCA=ROOT/'eval/results/e5_rcfh/rca_dataset_reported_loss.json'
OUT=ROOT/'eval/results/e5_rcfh/defihacklabs_80_t0_rca_comparison.json'
def parse(v): return v not in (None,'','-')
def main():
    t0={x['case_id']:x for x in json.loads(T0.read_text())['cases']}
    rca={x['case_id']:x for x in json.loads(RCA.read_text())['matches']}
    rows=[]
    for cid,x in t0.items():
        loss=parse(rca.get(cid,{}).get('reported_loss')); status=x['t0_status']
        rows.append({**x,'rca_reported_loss':rca.get(cid,{}).get('reported_loss'),'rca_loss_presence':'HARM' if loss else 'UNKNOWN','comparison':'AGREE_HARM' if loss and status=='HARM' else 'DISAGREE_T0_NO_HARM_BUT_RCA_LOSS' if loss and status=='NO_HARM' else 'NOT_TESTABLE'})
    subset=[x for x in rows if x['comparison']!='NOT_TESTABLE']; outcomes=Counter(x['comparison'] for x in subset)
    tp=outcomes.get('AGREE_HARM',0); predicted=sum(x['t0_status']=='HARM' for x in subset)
    out={'schema_version':1,'artifact':'defihacklabs-80-t0-rca-comparison-v1','scope':'80-case raw receipt-flow T0 versus incident-level RCA loss','case_count':80,'t0_counts':dict(Counter(x['t0_status'] for x in rows)),'rca_loss_cases':len(subset),'comparison_counts':dict(outcomes),'descriptive_subset_metrics':{'n':len(subset),'agree_harm':tp,'disagree':outcomes.get('DISAGREE_T0_NO_HARM_BUT_RCA_LOSS',0),'precision':tp/predicted if predicted else None,'recall':tp/len(subset) if subset else None},'warning':'RCA is incident-level and cannot be treated as transaction-level protected-harm ground truth; fidelity failure and missing RCA loss are abstentions.','cases':rows}
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'t0_counts':out['t0_counts'],'rca_loss_cases':len(subset),'comparison_counts':dict(outcomes),'metrics':out['descriptive_subset_metrics']},indent=2))
if __name__=='__main__': main()
