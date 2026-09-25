"""Independent explorer cross-check for source-explicit provenance batch."""
from __future__ import annotations
import json, os, urllib.parse, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def query(key, tx, chainid):
    params=urllib.parse.urlencode({'chainid':chainid,'module':'proxy','action':key,'txhash':tx,'apikey':os.environ['ETHERSCAN']})
    url='https://api.etherscan.io/v2/api?'+params
    with urllib.request.urlopen(url,timeout=12) as r: return json.loads(r.read())
def main():
    env={}
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1); env[k.strip()]=v.strip().strip('"').strip("'")
    os.environ.update({k:v for k,v in env.items() if k not in os.environ})
    p=ROOT/'eval/vnext/recovery/positive_provenance_batch_001.jsonl'; rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip() and json.loads(x).get('source_explicitly_identifies_exploit_tx')]
    out=[]
    for r in rows:
        tx=r['tx_hash']; rec={**r,'p1_source_explicit':True,'p2_explorer_tx':False,'p3_explorer_receipt':False,'explorer_error':None}
        try:
            chainid={'ethereum':'1','mainnet':'1','arbitrum':'42161','bsc':'56'}.get(str(r['chain']).lower())
            if not chainid: raise ValueError('unsupported explorer chain')
            tr=query('eth_getTransactionByHash',tx,chainid).get('result')
            rr=query('eth_getTransactionReceipt',tx,chainid).get('result')
            rec['p2_explorer_tx']=isinstance(tr,dict) and tr.get('hash','').lower()==tx.lower() and tr.get('blockNumber') is not None
            rec['p3_explorer_receipt']=isinstance(rr,dict) and rr.get('transactionHash','').lower()==tx.lower() and rr.get('blockNumber') is not None and rr.get('status') is not None
            rec['explorer_block']=tr.get('blockNumber') if isinstance(tr,dict) else None
            rec['explorer_receipt_status']=rr.get('status') if isinstance(rr,dict) else None
        except Exception as e: rec['explorer_error']=type(e).__name__+': '+str(e)
        rec['review_status']='PENDING_INCIDENT_MATCH' if rec['p2_explorer_tx'] and rec['p3_explorer_receipt'] else 'UNRESOLVED_PROVENANCE'
        out.append(rec)
    dest=ROOT/'eval/vnext/recovery'; (dest/'positive_a2_explorer_crosscheck.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    summary={'schema_version':1,'status':'CROSSCHECK_ONLY','records':len(out),'p2_pass':sum(x['p2_explorer_tx'] for x in out),'p3_pass':sum(x['p3_explorer_receipt'] for x in out),'promoted':0,'policy':'Explorer cross-check does not itself promote VERIFIED_ATTACK; P1 incident match remains manual.'}
    (dest/'positive_a2_explorer_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
