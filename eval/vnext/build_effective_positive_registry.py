"""Build an explicit modeling registry after fail-closed exclusions."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
EX={'defihacklabs-h2o-2025-03-14':'EXCLUDED_CANONICAL_AMBIGUITY','defihacklabs-olpc-2026-06-20':'EXCLUDED_CANONICAL_AMBIGUITY','defihacklabs-unprotectedarbbot-2026-07-30':'EXCLUDED_CHAIN_OR_P2_P3_PENDING'}
EX.update({i:'EXCLUDED_UNRESOLVED_CANONICAL' for i in ('defihacklabs-adsharesbridge-2026-05-15','defihacklabs-aztec-v1-2026-06-17','defihacklabs-bubai-2024-10-29','defihacklabs-hegicoptions-2025-02-23','defihacklabs-unilend-2025-01-12','defihacklabs-veth-2024-11-14')})
def main():
    src=ROOT/'corpus/vnext/positive_registry.jsonl'; sh=hashlib.sha256(src.read_bytes()).hexdigest(); rows=[json.loads(x) for x in src.read_text().splitlines() if x.strip()]
    effective=[]; excluded=[]
    for x in rows:
        if x['incident_id'] in EX: excluded.append({'incident_id':x['incident_id'],'status':'EXCLUDED_FROM_MODELING','reason_code':EX[x['incident_id']],'source_registry_sha256':sh})
        else: effective.append(x)
    d=ROOT/'corpus/vnext'; out=d/'positive_registry_effective.jsonl'; out.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in sorted(effective,key=lambda z:z['incident_id']))); ex=d/'positive_modeling_exclusions.jsonl'; ex.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in excluded))
    m={'schema_version':1,'status':'FROZEN_EFFECTIVE_PENDING_SPLIT_AUDIT','source_registry_sha256':sh,'effective_incidents':len(effective),'excluded_incidents':len(excluded),'effective_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'exclusions_sha256':hashlib.sha256(ex.read_bytes()).hexdigest(),'policy':'Original registry remains immutable; excluded incidents are retained with explicit fail-closed reasons.'}; (d/'positive_registry_effective_manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n'); print(json.dumps(m,indent=2,sort_keys=True))
if __name__=='__main__':main()
