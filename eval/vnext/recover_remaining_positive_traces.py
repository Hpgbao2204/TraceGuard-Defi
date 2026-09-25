"""Recover non-BSC missing positive traces into isolated vNext caches."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from core.env import load_dotenv
from eval.e1_crawl import Crawler
from eval.e1_common import load_cache_rows

ENV={'ethereum':'QUICKNODE_TRACE_RPC','arbitrum':'QUICKNODE_ARB','optimism':'QUICKNODE_OPT'}
ARCH={'ethereum':'ARCHIVE_RPC','arbitrum':'ARB_ARCHIVE_RPC','optimism':'OPTIMISM_ARCHIVE_RPC'}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--chain',choices=sorted(ENV),required=True); ap.add_argument('--tx',action='append'); args=ap.parse_args(); load_dotenv()
    rpc=os.environ.get(ARCH[args.chain]) or os.environ.get(ENV[args.chain])
    trace=os.environ.get(ENV[args.chain]) or rpc
    if not rpc: raise SystemExit(f'missing configured RPC for {args.chain}: {ARCH[args.chain]} / {ENV[args.chain]}')
    pos=[json.loads(x) for x in (ROOT/'corpus/vnext/positive_transactions.jsonl').read_text().splitlines() if x.strip() and json.loads(x).get('chain')==args.chain]
    if args.tx:
        wanted=set(args.tx); pos=[x for x in pos if x['tx_hash'] in wanted]
    cache=ROOT/f'eval/vnext/acquisition/{args.chain}_positive_trace_cache.jsonl'; progress=ROOT/f'eval/vnext/acquisition/{args.chain}_positive_trace_progress.csv'
    c=Crawler(rpc,trace_rpc_url=trace,cache_path=cache,progress_path=progress,workers=2,timeout=90,throttle=.2)
    entries=[{'tx_hash':x['tx_hash'],'block':None,'label':'attack','source':'vnext-positive','protocol':'unknown','attack_id':x['incident_id'],'attack_type':'vnext','gt_factors':[]} for x in pos]
    # Existing tx+receipt rows are not completion for this call-trace recovery.
    existing=load_cache_rows(cache) if cache.exists() else {}
    entries=[e for e in entries if existing.get(e['tx_hash'],{}).get('source') != 'callTracer']
    c.crawl(entries,resume=False)
    print(json.dumps({'chain':args.chain,'requested':len(pos),'stats':c.stats,'cache':str(cache.relative_to(ROOT))},sort_keys=True))
if __name__=='__main__': main()
