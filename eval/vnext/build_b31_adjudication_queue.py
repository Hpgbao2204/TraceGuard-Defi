"""Build official-label adjudication queue without converting reviewer opinions."""
from __future__ import annotations
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ALLOWED={'VERIFIED_BENIGN','KNOWN_MALICIOUS','PROTOCOL_MISUSE','WHITEHAT_RESCUE','UNCERTAIN'}
def main():
    src=ROOT/'corpus/vnext/independent_review_29_transactions.jsonl'; rows=[]
    for line in src.read_text().splitlines():
        x=json.loads(line); rows.append({'tx_hash':x['tx_hash'],'anchor_id':x['anchor_id'],'incident_id':x['incident_id'],'chain':x['chain'],'tx_block':x['tx_block'],'supporting_review':{'reviewer_id':x['reviewer_id'],'label':x['review_label'],'evidence':x['review_evidence']},'final_label':None,'adjudicator_id':None,'adjudicated_at':None,'adjudication_evidence':[],'labels_allowed':sorted(ALLOWED),'blindness_policy':'Model score/prediction omitted; supporting opinion is not a final label.'})
    d=ROOT/'corpus/vnext'; p=d/'hard_negative_pilot_adjudication_queue.jsonl'; p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows)); m={'schema_version':1,'stage':'B3.1','records':len(rows),'final_labels_allowed':sorted(ALLOWED),'source_submission_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'supporting_likely_benign':sum(x['supporting_review']['label']=='LIKELY_BENIGN' for x in rows),'final_verified_benign':0,'status':'PENDING_INDEPENDENT_ADJUDICATION'}; (d/'hard_negative_pilot_adjudication_manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n'); print(json.dumps(m,indent=2))
if __name__=='__main__': main()
