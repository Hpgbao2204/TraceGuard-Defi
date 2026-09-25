"""Build bounded manual provenance batch from RESOLVED_TX_ONLY rows."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    resolutions=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/positive_a1_resolution.jsonl').read_text().splitlines() if x.strip()]
    incidents={json.loads(x)['id']:json.loads(x) for x in (ROOT/'corpus/incidents.jsonl').read_text().splitlines() if x.strip()}
    rows=[]
    for r in resolutions:
        if r.get('status')!='RESOLVED_TX_ONLY': continue
        src=incidents[r['incident_id']]
        for result in r.get('results',[]):
            if not result.get('found'): continue
            rows.append({
                'incident_id':r['incident_id'],'tx_hash':result['hash'],'chain':r['chain'],
                'source_url':src.get('source_url'),'source_name':src.get('source'),
                'protocol':src.get('protocol'),'date':src.get('date'),'notes':src.get('notes'),
                'rpc_block':result.get('block'),'receipt_resolved':None,
                'source_explicitly_identifies_exploit_tx':None,'incident_match':None,
                'duplicate':None,'review_status':'PENDING_PROVENANCE','reason_code':None,
                'evidence_refs':[]
            })
    rows=rows[:30]
    out=ROOT/'eval/vnext/recovery/positive_provenance_batch_001.jsonl'
    out.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows))
    summary={'schema_version':1,'status':'PENDING_MANUAL_PROVENANCE','batch_id':'positive-provenance-001','record_count':len(rows),'policy':'No automatic promotion; reviewer must verify exploit identity, receipt, block, provenance, and duplicate status.'}
    (ROOT/'eval/vnext/recovery/positive_provenance_batch_001_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
