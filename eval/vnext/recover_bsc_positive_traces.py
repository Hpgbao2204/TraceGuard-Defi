"""Recover missing BSC positive traces into the isolated vNext cache."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.env import load_dotenv
from eval.e1_crawl import Crawler

def main():
    load_dotenv()
    rpc=os.environ.get('QUICKNODE_BNB')
    if not rpc: raise SystemExit('QUICKNODE_BNB is not configured')
    pos=[json.loads(x) for x in (ROOT/'corpus/vnext/positive_transactions.jsonl').read_text().splitlines() if x.strip() and json.loads(x).get('chain')=='bsc']
    cache=ROOT/'eval/vnext/acquisition/bsc_positive_trace_cache.jsonl'
    progress=ROOT/'eval/vnext/acquisition/bsc_positive_trace_progress.csv'
    c=Crawler(rpc, trace_rpc_url=rpc, cache_path=cache, progress_path=progress, workers=2, timeout=90, throttle=.2)
    c.crawl([{'tx_hash':x['tx_hash'],'block':None,'label':'attack','source':'vnext-positive','protocol':'unknown','attack_id':x['incident_id'],'attack_type':'vnext','gt_factors':[]} for x in pos], resume=True)
    print(json.dumps({'requested':len(pos),'stats':c.stats,'cache':str(cache.relative_to(ROOT))},sort_keys=True))
if __name__=='__main__': main()
