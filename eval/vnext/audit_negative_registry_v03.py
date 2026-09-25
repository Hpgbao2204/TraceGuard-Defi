"""Audit legacy benign rows for vNext negative-registry eligibility."""
import hashlib,json
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2]
def main():
    cache=ROOT/'eval/results/e1_trace_cache.jsonl'; rows=[]
    for line in cache.read_text().splitlines():
        try:x=json.loads(line)
        except:continue
        if x.get('label')=='benign': rows.append(x)
    eligible=[]; pending=[]
    for x in rows:
        has_source=bool(x.get('source') and x.get('source') not in ('legacy','unknown'))
        has_group=bool(x.get('incident_id') or x.get('attack_id') or x.get('protocol') not in (None,'','block-tx'))
        item={'tx_hash':x.get('tx_hash'),'chain':x.get('chain') or x.get('network'),'block':x.get('block'),'timestamp':x.get('timestamp'),'source':x.get('source'),'protocol':x.get('protocol'),'group_id':x.get('incident_id') or x.get('attack_id'),'label':0,'negative_tier':'ordinary','provenance_status':'PENDING_PROVENANCE'}
        (eligible if has_source and has_group else pending).append(item if has_source and has_group else {**item,'reason_code':'MISSING_INDEPENDENT_SOURCE_OR_GROUP_AUTHORITY'})
    out=ROOT/'eval/vnext/gates/gate_v0_3_negative_registry_audit.json'; out.parent.mkdir(parents=True,exist_ok=True)
    data={'schema_version':1,'status':'FAIL','source_cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'legacy_benign_rows':len(rows),'candidate_rows_with_minimum_metadata':len(eligible),'pending_provenance_rows':len(pending),'eligible_rows_are_not_promoted':True,'by_protocol':dict(Counter(x.get('protocol') or 'UNKNOWN' for x in rows)),'policy':'Legacy benign rows are not verified negatives without independent provenance and grouping authority; no model score used.'}
    out.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n'); (ROOT/'eval/vnext/gates/gate_v0_3_negative_pending.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in pending)); print(json.dumps(data,indent=2))
if __name__=='__main__':main()
