"""Triage A1 unresolved rows; does not promote any attack label."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    src=ROOT/'eval/vnext/recovery/positive_a1_resolution.jsonl'
    rows=[json.loads(x) for x in src.read_text().splitlines() if x.strip()]
    out=[]
    for r in rows:
        results=r.get('results',[]); found=sum(bool(x.get('found')) for x in results)
        if r.get('status')=='RESOLVED_TX_ONLY': kind='RESOLVED_TX_ONLY_REQUIRES_PROVENANCE'
        elif r.get('reason_code')=='CHAIN_RPC_NOT_CONFIGURED': kind='RPC_NOT_CONFIGURED_OR_OUT_OF_SCOPE'
        elif found and found < len(results): kind='PARTIALLY_RESOLVED'
        elif any(x.get('error') for x in results): kind='RPC_TRANSIENT_OR_PROVIDER_ERROR'
        else: kind='NOT_FOUND_AFTER_CONFIGURED_RPC'
        out.append({**r,'triage_class':kind,'resolved_hash_count':found,'hash_count':len(results)})
    dest=ROOT/'eval/vnext/recovery'; dest.mkdir(parents=True,exist_ok=True)
    (dest/'positive_a1_triage.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    c=Counter(x['triage_class'] for x in out)
    summary={'schema_version':1,'status':'TRIAGE_ONLY','counts':dict(c),'policy':'Triage routes cases; it never promotes verified attack status.'}
    (dest/'positive_a1_triage_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
