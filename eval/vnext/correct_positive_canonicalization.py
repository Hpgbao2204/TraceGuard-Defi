"""Produce a corrected pending registry; never silently promote multi-tx rows."""
import json, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FIXES={
 'defihacklabs-unprotectedarbbot-2026-07-30': {'chain':'base','tx_hashes':['0xe831f3991132cbaffbb4a3738da7d1e254a6c02f0adce605a333229a61e27ad7'],'status':'CHAIN_METADATA_CORRECTED_PENDING_P2_P3'},
 'defihacklabs-h2o-2025-03-14': {'tx_hashes':[],'status':'PENDING_CANONICAL_REVIEW'},
 'defihacklabs-olpc-2026-06-20': {'tx_hashes':[],'status':'PENDING_CANONICAL_REVIEW'},
}
def main():
    reg=[json.loads(x) for x in (ROOT/'corpus/vnext/positive_registry.jsonl').read_text().splitlines() if x.strip()]
    out=[]
    for x in reg:
        y=dict(x); fix=FIXES.get(x['incident_id'])
        if fix:
            y.update(fix); y['verification']='pending_canonical_repair'; y['correction_reason']='source-bound chain/role issue; no automatic multi-tx selection'
            y['evidence_refs']=[]; y['p2_status']='PENDING'; y['p3_status']='PENDING'
        out.append(y)
    path=ROOT/'corpus/vnext/positive_registry_corrected_pending.jsonl'; path.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in sorted(out,key=lambda z:z['incident_id'])))
    manifest={'schema_version':1,'status':'PENDING_REVIEW','source_sha256':hashlib.sha256((ROOT/'corpus/vnext/positive_registry.jsonl').read_bytes()).hexdigest(),'output_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'corrections':FIXES,'policy':'Candidate correction only; official frozen registry is not overwritten.'}
    (ROOT/'corpus/vnext/positive_registry_corrected_pending_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n'); print(json.dumps(manifest,indent=2,sort_keys=True))
if __name__=='__main__': main()
