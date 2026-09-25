"""Freeze audited metadata-only ordinary negatives without mutating candidates."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    src=ROOT/'negatives/negative_metadata_candidates_v1.jsonl'; rows=[json.loads(x) for x in src.read_text().splitlines() if x.strip()]
    hs=[x['tx_hash'].lower() for x in rows]
    assert len(rows)==4000 and len(set(hs))==4000
    assert all(x.get('group_id') and x.get('provenance_status')=='METADATA_RECEIPT_VERIFIED' and x.get('receipt_status') in ('0x1',1) for x in rows)
    out=ROOT/'negatives/negative_registry_v1.jsonl'; out.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows))
    m={'schema_version':1,'status':'FROZEN','rows':len(rows),'unique_hashes':len(set(hs)),'source_candidates_sha256':sha(src),'registry_sha256':sha(out),'policy_sha256':sha(ROOT/'negative_sampling_policy_v1.json'),'positive_metadata_sha256':sha(ROOT/'positives/positive_metadata_v1.jsonl'),'chains':sorted({x['chain'] for x in rows})}
    (ROOT/'negatives/negative_registry_v1_manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n'); print(json.dumps(m,indent=2,sort_keys=True))
if __name__=='__main__': main()
