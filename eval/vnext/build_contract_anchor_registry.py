"""Build fail-closed anchor registry; never infer vulnerable contracts from txs."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    files=sorted((ROOT/'eval/vnext/recovery').glob('positive_provenance_promotions_v*.jsonl'))
    rows=[]
    for p in files:
        for line in p.read_text().splitlines():
            if not line.strip(): continue
            x=json.loads(line)
            rows.append({'incident_id':x['incident_id'],'attack_tx':x['tx_hash'],'chain':x['chain'],'source_snapshot':x.get('source_path'),'source_snapshot_sha256':x.get('source_snapshot_sha256'),'exact_vulnerable_contract':None,'proxy_or_implementation':None,'protocol_owned_contracts':[],'relevant_functions':[],'anchor_status':'PENDING_MANUAL_ANCHOR_REVIEW','policy':'Do not infer contract anchors from transaction or source filename.'})
    d=ROOT/'corpus/vnext'; d.mkdir(exist_ok=True); p=d/'contract_anchor_registry.jsonl'; p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows)); print(json.dumps({'records':len(rows),'anchored':0,'status':'PENDING_MANUAL_ANCHOR_REVIEW'},indent=2))
if __name__=='__main__': main()
