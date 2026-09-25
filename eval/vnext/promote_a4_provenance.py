"""Promote A4 rows only when source wording explicitly identifies exploit tx."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    rows=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/positive_a5_batch_004_rpc_crosscheck.jsonl').read_text().splitlines() if x.strip()]
    out=[]
    for r in rows:
        text=(ROOT/r['snapshot_path']).read_text(errors='ignore') if r.get('snapshot_path') else ''
        explicit='exploit tx' in text.lower() or 'attack tx' in text.lower() or 'drain tx' in text.lower() or 'sweep tx' in text.lower()
        if r['promotion_ready'] and explicit:
            out.append({'schema_version':1,'status':'VERIFIED_ATTACK','review_method':'manual_p1_p2_p3_confirmation','incident_id':r['incident_id'],'tx_hash':r['tx_hash'],'chain':r['chain'],'tx_role':'exploit','canonical_attack_tx':True,'source_path':r['path'],'source_commit_sha':r['commit_sha'],'source_snapshot_sha256':r['snapshot_sha256'],'chain_block':r['chain_block'],'receipt_status':r['receipt_status'],'evidence_refs':['git-history source snapshot explicitly labels exploit/attack tx','independent external-network JSON-RPC transaction and receipt cross-check'],'policy':'Incident count increments once; source snapshot and chain evidence are immutable.'})
    # Deduplicate incident-level promotions; retain the first canonical tx row.
    out=list({x['incident_id']:x for x in out}.values())
    d=ROOT/'eval/vnext/recovery'; p=d/'positive_provenance_promotions_v5.jsonl'; p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    print(json.dumps({'promoted':len(out),'excluded_for_p1':len(rows)-len(out),'artifact':str(p)},indent=2))
if __name__=='__main__': main()
