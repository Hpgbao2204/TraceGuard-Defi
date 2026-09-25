"""Cross-check Git-history source snapshots against explorer tx/receipt."""
from __future__ import annotations
import json,os,urllib.parse,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CHAIN={'ethereum':'1','mainnet':'1','arbitrum':'42161','bsc':'56','polygon':'137','optimism':'10','avalanche':'43114','fantom':'250'}
def q(action,tx,cid,key):
    u='https://api.etherscan.io/v2/api?'+urllib.parse.urlencode({'chainid':cid,'module':'proxy','action':action,'txhash':tx,'apikey':key})
    with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'TraceGuard-vNext/1.0'}),timeout=12) as r:return json.loads(r.read()).get('result')
def main():
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
    key=os.environ.get('ETHERSCAN'); rows=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/source_provenance_git_history.jsonl').read_text().splitlines() if x.strip()]
    out=[]
    for r in rows:
        rec={**r,'p2_explorer_tx':False,'p3_explorer_receipt':False,'explorer_error':None}
        try:
            cid=CHAIN.get(str(r.get('chain')).lower())
            if not key or not cid: raise ValueError('missing key or unsupported chain')
            tx=q('eth_getTransactionByHash',r['tx_hash'],cid,key); receipt=q('eth_getTransactionReceipt',r['tx_hash'],cid,key)
            rec['p2_explorer_tx']=isinstance(tx,dict) and str(tx.get('hash','')).lower()==r['tx_hash'].lower() and tx.get('blockNumber') is not None
            rec['p3_explorer_receipt']=isinstance(receipt,dict) and str(receipt.get('transactionHash','')).lower()==r['tx_hash'].lower() and receipt.get('blockNumber') is not None and receipt.get('status') is not None
            rec['explorer_block']=tx.get('blockNumber') if isinstance(tx,dict) else None; rec['explorer_receipt_status']=receipt.get('status') if isinstance(receipt,dict) else None
        except Exception as e: rec['explorer_error']=type(e).__name__+': '+str(e)
        rec['promotion_ready']=rec['status']=='SOURCE_SNAPSHOT_READY' and rec['hash_explicit_in_snapshot'] and rec['p2_explorer_tx'] and rec['p3_explorer_receipt']
        out.append(rec)
    d=ROOT/'eval/vnext/recovery'; (d/'source_git_explorer_crosscheck.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    s={'schema_version':1,'status':'CROSSCHECK_ONLY','records':len(out),'p2_pass':sum(x['p2_explorer_tx'] for x in out),'p3_pass':sum(x['p3_explorer_receipt'] for x in out),'promotion_ready':sum(x['promotion_ready'] for x in out),'policy':'P1 incident-role review remains mandatory; no auto-promotion.'}
    (d/'source_git_explorer_crosscheck_summary.json').write_text(json.dumps(s,indent=2,sort_keys=True)+'\n'); print(json.dumps(s,indent=2))
if __name__=='__main__': main()
