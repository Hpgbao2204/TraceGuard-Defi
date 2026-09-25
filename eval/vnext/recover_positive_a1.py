"""Bounded Gate-A recovery for attack rows with tx hashes and no current verification."""
from __future__ import annotations
import json, os, time
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.env import load_dotenv, resolve_rpc
from core.rpc import RpcClient, RpcError

def hashes(r):
    return [h for h in r.get('tx_hashes',[]) if isinstance(h,str)]

def rpc_candidates(chain):
    chain=str(chain).lower()
    if chain in ('ethereum','mainnet'):
        names=['ARCHIVE_RPC','CHAINSTACK_ETH_HTTP_URL','ANKR_ETHEREUM','NODIES','DRPC','ONFINALITY','BOAR','ETOX']
        return [os.environ[n] for n in names if os.environ.get(n)]
    if chain=='arbitrum':
        return [x for x in [os.environ.get('ARB_ARCHIVE_RPC'),os.environ.get('ANKR_ARB')] if x]
    key=os.environ.get('ANKR_KEY')
    if key and chain in ('bsc','polygon','optimism','avalanche','fantom'):
        return [f'https://rpc.ankr.com/{chain}/{key}']
    return []

def main():
    load_dotenv(); clients={}
    rows=[json.loads(x) for x in (ROOT/'corpus/incidents.jsonl').read_text().splitlines() if x.strip()]
    candidates=[r for r in rows if r.get('class')=='attack' and r.get('verified')!='onchain' and hashes(r)]
    out=[]; stats={'candidates':len(candidates),'resolved_tx_only':0,'rejected':0,'unresolved':0,'chains_without_rpc':0}
    for i,r in enumerate(candidates,1):
        chain=str(r.get('chain','')).lower()
        candidates=rpc_candidates(chain)
        if not candidates:
            out.append({'incident_id':r.get('id'),'chain':r.get('chain'),'tx_hashes':hashes(r),'status':'UNRESOLVED','reason_code':'CHAIN_RPC_NOT_CONFIGURED'})
            stats['unresolved']+=1; stats['chains_without_rpc']+=1; continue
        for n,url in enumerate(candidates):
            clients.setdefault(url,RpcClient(url, timeout=6.0, attempts=1, backoff_base=0.0))
        results=[]
        for h in hashes(r):
            found=None; errors=[]
            for url in candidates:
                try:
                    tx=clients[url].eth_get_transaction(h)
                    if tx is not None:
                        found=tx; break
                except RpcError as e: errors.append(str(e))
            results.append({'hash':h,'found':found is not None,'block':found.get('blockNumber') if found else None,'fallbacks_tried':len(candidates),'errors':errors[-1:]})
            time.sleep(.15)
        found=bool(results) and all(x.get('found') for x in results)
        status='RESOLVED_TX_ONLY' if found else 'UNRESOLVED'
        reason='TX_RESOLVED_REQUIRES_INCIDENT_PROVENANCE_REVIEW' if found else 'TX_NOT_RESOLVED'
        stats['resolved_tx_only' if found else 'unresolved']+=1
        out.append({'incident_id':r.get('id'),'chain':r.get('chain'),'tx_hashes':hashes(r),'status':status,'reason_code':reason,'results':results,'source_url':r.get('source_url')})
        print(f'[{i}/{len(candidates)}] {r.get("id")}: {status}', flush=True)
    dest=ROOT/'eval/vnext/recovery'; dest.mkdir(parents=True,exist_ok=True)
    (dest/'positive_a1_resolution.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    (dest/'positive_a1_summary.json').write_text(json.dumps({'schema_version':1,'status':'RESOLUTION_ONLY','stats':stats,'policy':'TX resolution is not attack verification; provenance review remains required.'},indent=2,sort_keys=True)+'\n')
    print(json.dumps(stats,indent=2))

if __name__=='__main__': main()
