"""Freeze the completed supplementary review round without replay."""
import hashlib, json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SIDE=ROOT/'corpus/annotations/review_bundles_supplementary/m6_supplementary_adjudication_reviewer_c_v2.jsonl'
LEADS=ROOT/'eval/results/m6_supplementary_candidate_leads.json'
OUT=ROOT/'eval/results/m6_supplementary_freeze_manifest.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    rows=[json.loads(x) for x in SIDE.read_text().splitlines() if x.strip()]
    try: commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except Exception: commit='unknown'
    result={'schema_version':1,'status':'FROZEN_NO_RELEASE_POSITIVE','freeze_reason':'OUT_OF_RELEASE_OPERATOR_SCOPE','case_count':len(rows),'adjudicated_count':len(rows),'release_positive_count':0,'cases':[{'case_id':r['case_id'],'tx_hash':r['tx_hash'],'final_root_cause_gt':r['root_cause_gt'],'flash_loan_role':r['flash_loan_role'],'oracle_subtype':r['oracle_subtype'],'status':'OUT_OF_RELEASE_OPERATOR_SCOPE'} for r in rows],'source_sidecar_sha256':sha(SIDE),'source_leads_sha256':sha(LEADS),'freeze_source_commit':commit,'replay_authorized':False}
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); print(json.dumps({'case_count':len(rows),'release_positive_count':0,'sha256':sha(OUT),'out':str(OUT)},indent=2))
if __name__=='__main__': main()
