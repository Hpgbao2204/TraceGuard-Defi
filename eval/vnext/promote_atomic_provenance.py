"""Record explicit human-reviewed promotion for Atomic; keep source corpus immutable."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    cross=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/source_git_explorer_crosscheck.jsonl').read_text().splitlines() if x.strip()]
    row=next(x for x in cross if x['incident_id']=='defihacklabs-atomic-2026-08-07')
    assert row['promotion_ready'] and row['hash_explicit_in_snapshot']
    result={
      'schema_version':1,'status':'VERIFIED_ATTACK','review_method':'manual_p1_p2_p3_confirmation',
      'incident_id':row['incident_id'],'tx_hash':row['tx_hash'],'chain':row['chain'],'tx_role':'exploit','canonical_attack_tx':True,
      'source_path':row['path'],'source_commit_sha':row['commit_sha'],'source_snapshot_sha256':row['snapshot_sha256'],
      'explorer_block':row['explorer_block'],'explorer_receipt_status':row['explorer_receipt_status'],
      'evidence_refs':['source_snapshot:line 9 explicitly labels hash Exploit tx','explorer:transaction and receipt P2/P3 pass'],
      'policy':'Incident count increments once; transaction row remains grouped by incident_id. No automatic promotion of other rows.'}
    d=ROOT/'eval/vnext/recovery'; (d/'positive_provenance_promotions_v1.jsonl').write_text(json.dumps(result,sort_keys=True)+'\n'); print(json.dumps(result,indent=2))
if __name__=='__main__': main()
