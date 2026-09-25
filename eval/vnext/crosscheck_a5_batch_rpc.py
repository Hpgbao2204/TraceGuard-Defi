"""Bounded external RPC P2/P3 cross-check for A5 batch 001."""
from __future__ import annotations
import json,os,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PUBLIC={'ethereum':['https://cloudflare-eth.com'],'bsc':['https://bsc-dataseed.binance.org'],'optimism':['https://mainnet.optimism.io'],'base':['https://mainnet.base.org'],'arbitrum':['https://arb1.arbitrum.io/rpc'],'polygon':['https://polygon-rpc.com'],'avalanche':['https://api.avax.network/ext/bc/C/rpc']}
def rpc(url,method,tx):
    body=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':[tx]}).encode(); req=urllib.request.Request(url,body,{'Content-Type':'application/json','User-Agent':'TraceGuard-vNext/1.0'})
    with urllib.request.urlopen(req,timeout=4) as r: return json.load(r).get('result')
def main():
    rows=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/positive_a5_git_batch_004.jsonl').read_text().splitlines() if x.strip()]; out=[]
    for r in rows:
        urls=list(PUBLIC.get(r['chain'],[])); env={'ethereum':'ARCHIVE_RPC','arbitrum':'ARB_ARCHIVE_RPC'}.get(r['chain'])
        if env and os.environ.get(env): urls.insert(0,os.environ[env])
        item={**r,'p2_chain_inclusion':False,'p3_receipt':False,'rpc_attempts':0,'rpc_provider_class':'external-network-fallback','rpc_error':None}
        for u in urls:
            try:
                item['rpc_attempts']+=1; tx=rpc(u,'eth_getTransactionByHash',r['tx_hash']); rec=rpc(u,'eth_getTransactionReceipt',r['tx_hash'])
                if isinstance(tx,dict) and tx.get('blockNumber') and isinstance(rec,dict) and rec.get('transactionHash','').lower()==r['tx_hash'].lower() and rec.get('blockNumber') and rec.get('status') is not None:
                    item.update({'p2_chain_inclusion':True,'p3_receipt':True,'chain_block':tx['blockNumber'],'receipt_status':rec['status'],'rpc_error':None}); break
            except Exception as e: item['rpc_error']=type(e).__name__
        item['promotion_ready']=bool(item['status']=='SOURCE_SNAPSHOT_READY' and item.get('hash_explicit_in_snapshot') and item['p2_chain_inclusion'] and item['p3_receipt'])
        out.append(item); print(len(out), r['incident_id'], item['p2_chain_inclusion'], flush=True)
    d=ROOT/'eval/vnext/recovery'; p=d/'positive_a5_batch_004_rpc_crosscheck.jsonl'; p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    ready={x['incident_id'] for x in out if x['promotion_ready']}
    s={'schema_version':1,'stage':'A5-P2-P3','records':len(out),'p2_pass':sum(x['p2_chain_inclusion'] for x in out),'p3_pass':sum(x['p3_receipt'] for x in out),'promotion_ready_rows':sum(x['promotion_ready'] for x in out),'promotion_ready_unique_incidents':len(ready),'status':'CROSSCHECK_ONLY_NO_PROMOTION'}
    (d/'positive_a5_batch_004_rpc_crosscheck_summary.json').write_text(json.dumps(s,indent=2,sort_keys=True)+'\n'); print(json.dumps(s,indent=2))
if __name__=='__main__': main()
