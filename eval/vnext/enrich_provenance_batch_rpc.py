"""Add objective receipt/block checks to bounded provenance batch; no label promotion."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from core.env import load_dotenv
from core.rpc import RpcClient, RpcError
def main():
    load_dotenv(); urls=[os.environ.get(k) for k in ('ARCHIVE_RPC','CHAINSTACK_ETH_HTTP_URL','ANKR_ETHEREUM','NODIES','DRPC','ONFINALITY','BOAR','ETOX') if os.environ.get(k)]
    clients=[RpcClient(u,timeout=6,attempts=1,backoff_base=0) for u in urls]
    p=ROOT/'eval/vnext/recovery/positive_provenance_batch_001.jsonl'; rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    for r in rows:
        receipt=None; errors=[]
        for c in clients:
            try:
                receipt=c.eth_get_receipt(r['tx_hash'])
                if receipt is not None: break
            except RpcError as e: errors.append(str(e))
        r['receipt_resolved']=receipt is not None
        r['receipt_status']=(receipt or {}).get('status') if receipt else None
        r['source_explicitly_identifies_exploit_tx']=r['tx_hash'].lower() in (r.get('notes') or '').lower()
        if receipt is None: r['reason_code']='RECEIPT_NOT_RESOLVED'
        elif not r['source_url']: r['reason_code']='MISSING_SOURCE_URL'
        elif not r['source_explicitly_identifies_exploit_tx']: r['reason_code']='SOURCE_TX_ROLE_REQUIRES_REVIEW'
        else: r['reason_code']='MANUAL_INCIDENT_MATCH_REQUIRED'
        r['rpc_provider_count']=len(clients); r['rpc_error_count']=len(errors)
    p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows))
    print(json.dumps({'batch_id':'positive-provenance-001','records':len(rows),'receipt_resolved':sum(bool(r['receipt_resolved']) for r in rows),'source_explicit_hash':sum(bool(r['source_explicitly_identifies_exploit_tx']) for r in rows)},indent=2))
if __name__=='__main__': main()
