"""B2 frozen-rule filtering; fail closed when B1 lacks shape evidence."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    rows=[json.loads(x) for x in (ROOT/'corpus/vnext/historical_anchor_transactions.jsonl').read_text().splitlines() if x.strip()]; candidates=[]; rejects=[]
    for r in rows:
        # B1 no-logs acquisition deliberately cannot establish attack shape.
        if not any(k in r for k in ('log_events','trace','call_depth','transfer_count')):
            rejects.append({**r,'b2_status':'REJECTED','reason_code':'MISSING_OBJECTIVE_SHAPE_EVIDENCE'}); continue
        logs=r.get('log_events') or []
        if len(logs) >= 3:
            candidates.append({**r,'b2_status':'CANDIDATE','shape_rule':'log_events>=3','shape_features':{'log_event_count':len(logs)}})
        else:
            rejects.append({**r,'b2_status':'REJECTED','reason_code':'SHAPE_BELOW_FROZEN_THRESHOLD','shape_features':{'log_event_count':len(logs)}})
    d=ROOT/'corpus/vnext'; (d/'hard_negative_candidates.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in candidates)); g=ROOT/'eval/vnext/gates'; (g/'gate_b_b2_rejections.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rejects)); s={'schema_version':1,'stage':'B2','input_rows':len(rows),'candidates':len(candidates),'rejected':len(rejects),'reason_counts':{'MISSING_OBJECTIVE_SHAPE_EVIDENCE':sum(x['reason_code']=='MISSING_OBJECTIVE_SHAPE_EVIDENCE' for x in rejects),'SHAPE_BELOW_FROZEN_THRESHOLD':sum(x['reason_code']=='SHAPE_BELOW_FROZEN_THRESHOLD' for x in rejects)},'model_score_used':False,'shape_rule':'log_events>=3','status':'CANDIDATES_READY_FOR_BLIND_PILOT' if candidates else 'NO_CANDIDATES'}; (g/'gate_b_b2_shape_summary.json').write_text(json.dumps(s,indent=2,sort_keys=True)+'\n'); print(json.dumps(s,indent=2))
if __name__=='__main__': main()
