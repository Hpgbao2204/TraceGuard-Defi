"""B1: enumerate pre-attack direct history for verified anchors only."""
from __future__ import annotations
import json,os,urllib.parse,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CHAIN={'ethereum':'1','bsc':'56','optimism':'10','arbitrum':'42161','base':'8453','polygon':'137'}
ANCHORS=[
 ('defihacklabs-aic-2026-08-03','bsc','0xc0DC449De632586A00409873521AFC251aC5cE74',113782392),
 ('defihacklabs-aic-2026-08-03','bsc','0x974C0078740480aE830D379fDB8d5f441C9dDC75',113782392),
 ('defihacklabs-moke-2026-08-02','bsc','0x684D722EbF8980f49492f631f56765DD4Fb302A7',113652609),
 ('defihacklabs-lula-2026-07-26','bsc','0xf0b36389a12a28be1280c0eC2a4bbc76889d6a96',112655390),
 ('defihacklabs-pro-token-2026-07-25','bsc','0x63844BD4BFad910B1643713302a1cC1ed20d50c3',112654014),
 ('defihacklabs-crowdringcircle-2026-07-16','bsc','0xd8799A644850c065388c22DF4eE0C28472922526',110301524),
]
def main():
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
    key=os.getenv('ETHERSCAN'); out=[]; failures=[]
    for iid,chain,address,attack_block in ANCHORS:
        if not key: failures.append({'anchor':address,'reason':'API_KEY_NOT_CONFIGURED'}); continue
        q={'chainid':CHAIN[chain],'module':'account','action':'txlist','address':address,'startblock':0,'endblock':attack_block-1,'page':1,'offset':10000,'sort':'asc','apikey':key}
        url='https://api.etherscan.io/v2/api?'+urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'TraceGuard-vNext/1.0'}),timeout=20) as h: payload=json.loads(h.read())
            result=payload.get('result',[])
            if not isinstance(result,list): failures.append({'anchor':address,'reason':'EXPLORER_RESPONSE','status':payload.get('status'),'message':payload.get('message')}); continue
            for tx in result:
                out.append({'incident_id':iid,'anchor_address':address,'chain':chain,'attack_block':attack_block,'deployment_block':None,'window_start_unknown':True,'tx_hash':tx.get('hash'),'tx_block':int(tx['blockNumber']),'tx_timestamp':int(tx['timeStamp']) if tx.get('timeStamp') else None,'interaction_type':'direct','matched_anchor_ids':[address],'source':'explorer_account_txlist'})
        except Exception as e: failures.append({'anchor':address,'reason':type(e).__name__})
    merged={}
    for x in out:
        k=(x['chain'],x['tx_hash']); merged.setdefault(k,x); merged[k]['matched_anchor_ids']=sorted(set(merged[k]['matched_anchor_ids']+[x['anchor_address']]))
    out=sorted(merged.values(),key=lambda x:(x['chain'],x['tx_block'],x['tx_hash']))
    d=ROOT/'corpus/vnext'; d.mkdir(exist_ok=True); (d/'historical_anchor_transactions.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    g=ROOT/'eval/vnext/gates'; (g/'gate_b_b1_rejections.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in failures))
    s={'schema_version':1,'stage':'B1','anchors_attempted':len(ANCHORS),'anchors_with_history':len({x['anchor_address'] for x in out}),'total_raw_transactions':sum(1 for x in out),'unique_transactions':len(out),'direct_count':len(out),'internal_trace_count':0,'pre_attack_count':sum(x['tx_block']<x['attack_block'] for x in out),'rpc_or_explorer_failures':len(failures),'note':'Enumeration only; no benign label or model-score filtering.'}
    (g/'gate_b_b1_enumeration_summary.json').write_text(json.dumps(s,indent=2,sort_keys=True)+'\n'); print(json.dumps(s,indent=2))
if __name__=='__main__': main()
